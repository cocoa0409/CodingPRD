"""Two effectivity windows with opposite endpoint conventions: half-open price-file
windows where adjacency is legal, and closed certification intervals where a shared
endpoint collides."""
from test_helpers import (
    PRICING_ADMIN,
    WARRANTY_ADMIN,
    ApiErrorId,
    add_price_file_line,
    api_client,
    assert_same_instant,
    list_certifications,
    make_account,
    make_certification,
    make_part,
    make_price_file,
    make_pricing_tier,
    publish_price_file,
    read_certification,
    read_credit_summary,
    read_part,
    read_price_file,
    set_clock,
    technician_certification_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Shared setups
# ---------------------------------------------------------------------------

def _published_august_file_and_two_drafts():
    """August's published file covers 2026-08-01 up to 2026-09-01. One draft picks
    up exactly where it ends; another sits enclosed inside it."""
    part = make_part(
        part_number="W10-PUMP", oem_code="WHIRLPOOL",
        description="Drain pump assembly", category="MECHANICAL",
        list_price_cents=12999, weight_grams=5200,
    )
    august = make_price_file(
        20260801,
        effective_at="2026-08-01T00:00:00Z",
        effective_until="2026-09-01T00:00:00Z",
    )
    add_price_file_line(august, part, 13000)
    publish_price_file(august["id"])

    set_clock("2026-09-01T00:00:00Z")

    adjacent = make_price_file(20260901, effective_at="2026-09-01T00:00:00Z")
    add_price_file_line(adjacent, part, 13500)

    enclosed = make_price_file(
        20260815,
        effective_at="2026-08-15T00:00:00Z",
        effective_until="2026-08-20T00:00:00Z",
    )
    add_price_file_line(enclosed, part, 14000)

    return {
        "part": part, "august": august, "adjacent": adjacent, "enclosed": enclosed,
    }


def _account_with_a_certification_ending_on_the_first_of_june():
    """One ADVANCED certification covering 2026-01-01 through 2026-06-01
    inclusive."""
    tier = make_pricing_tier(
        tier_code="GOLD", name="Gold Contract",
        electrical=0.15, mechanical=0.20, cosmetic=0.25, sealed_system=0.10,
        min_annual_volume_cents=5000000,
    )
    account = make_account(
        tier, business_name="Ruiz Appliance Service",
        oem_authorizations=["WHIRLPOOL"], credit_terms="NET_30",
        credit_limit_cents=10000000, core_liability_limit_cents=5000000,
    )
    first = make_certification(
        account, technician_name="Dana Ruiz", oem_code="WHIRLPOOL",
        cert_level="ADVANCED",
        training_completed_at="2026-01-01T00:00:00Z",
        expires_at="2026-06-01T00:00:00Z",
    )
    return {"account": account, "first": first}


# ---------------------------------------------------------------------------
# Half-open price-file windows
# ---------------------------------------------------------------------------

class TestPriceFileWindowsAreHalfOpen:

    def test_a_file_starting_exactly_where_another_ends_publishes_cleanly(self):
        """PRD §3.7: "The window is **half-open**: it covers `effective_at` and
        everything up to but not including `effective_until`."
        PRD §3.7: "Because the earlier window excludes its own end instant, a file
        ending exactly where another begins does not collide at all."
        PRD §3.7: "Treating a null `effective_until` as unbounded on the right, an
        existing published file and the publishing file conflict when the existing
        file's `effective_at` falls strictly before the publishing file's window end
        **and** the publishing file's `effective_at` falls strictly before the
        existing file's window end."

        Design: Difficulty/resource_temporal_overlap/price_file_windows_are_half_open_so_adjacency_passes_and_enclosure_fails
        """
        world = _published_august_file_and_two_drafts()

        response = api_client.publish_price_file(
            world["adjacent"]["id"], PRICING_ADMIN
        )
        published = validate_success(response, 200)
        assert published["price_file_status"] == "PUBLISHED"
        assert published["effective_until"] is None, (
            "an open-ended file keeps its null end after publication"
        )

        august = read_price_file(world["august"]["id"])
        assert august["price_file_status"] == "PUBLISHED", (
            f"the earlier file had an explicit end, so it is not auto-closed, got "
            f"{august['price_file_status']}"
        )
        assert_same_instant(
            august["effective_until"], "2026-09-01T00:00:00Z", "effective_until"
        )

        assert read_part(world["part"]["id"])["list_price_cents"] == 13500, (
            "the publication writes the new list price onto the part"
        )

    def test_a_file_enclosed_inside_a_published_window_is_refused(self):
        """PRD §3.7: "Any other conflict is rejected with
        `ERR_PRICE_WINDOW_OVERLAP`."
        PRD §3.7: "**Window reconciliation** works per shared part, and only
        against files whose `price_file_status` is `PUBLISHED` — draft, superseded,
        and rolled-back files are ignored entirely, and files touching disjoint
        parts never collide however their windows sit."

        Design: Difficulty/resource_temporal_overlap/price_file_windows_are_half_open_so_adjacency_passes_and_enclosure_fails
        """
        world = _published_august_file_and_two_drafts()
        validate_success(
            api_client.publish_price_file(world["adjacent"]["id"], PRICING_ADMIN), 200
        )

        response = api_client.publish_price_file(
            world["enclosed"]["id"], PRICING_ADMIN
        )
        validate_error(response, ApiErrorId.ERR_PRICE_WINDOW_OVERLAP)

        enclosed = read_price_file(world["enclosed"]["id"])
        assert enclosed["price_file_status"] == "DRAFT"
        assert enclosed["published_at"] is None

        assert read_part(world["part"]["id"])["list_price_cents"] == 13500, (
            "the refused publication wrote nothing onto the part"
        )


# ---------------------------------------------------------------------------
# Closed certification intervals
# ---------------------------------------------------------------------------

class TestCertificationIntervalsAreClosed:

    def test_a_renewal_trained_on_the_expiry_instant_collides(self):
        """PRD §3.2: "The interval is **closed** — both endpoints count as covered
        — and `training_completed_at` must fall strictly before `expires_at` or the
        request is rejected with `ERR_CERT_INTERVAL_INVALID`."
        PRD §3.2: "Two closed intervals collide when the new certification's
        `training_completed_at` falls at or before the existing one's `expires_at`
        **and** the existing one's `training_completed_at` falls at or before the
        new one's `expires_at`; a collision is rejected with
        `ERR_CERT_WINDOW_OVERLAP`."
        PRD §3.2: "Merely touching endpoints do collide here: a certification
        expiring exactly at one instant and a renewal trained exactly at that same
        instant overlap on that instant and are refused."

        Design: Difficulty/resource_temporal_overlap/certification_windows_are_closed_so_a_touching_endpoint_collides
        """
        world = _account_with_a_certification_ending_on_the_first_of_june()

        response = api_client.create_technician_certification(
            technician_certification_payload(
                world["account"]["id"],
                technician_name="Dana Ruiz",
                oem_code="WHIRLPOOL",
                cert_level="ADVANCED",
                training_completed_at="2026-06-01T00:00:00Z",
                expires_at="2027-01-01T00:00:00Z",
            ),
            WARRANTY_ADMIN,
        )
        validate_error(response, ApiErrorId.ERR_CERT_WINDOW_OVERLAP)

        rows = list_certifications(servicer_account_id=world["account"]["id"])
        assert len(rows) == 1, (
            f"the refused renewal must not be persisted, got {len(rows)} row(s)"
        )

    def test_a_renewal_trained_one_day_later_is_accepted(self):
        """PRD §3.2: "Whether a certification actually grants anything is captured
        by `is_effective`, which is true only when `cert_status` is `ACTIVE` **and**
        `training_completed_at` falls at or before the logical clock **and**
        `expires_at` falls at or after the logical clock."
        PRD §3.2: "Certifications also expire without anyone asking: the periodic
        account review described in §3.5 moves every `ACTIVE` certification whose
        `expires_at` lies in the past to `EXPIRED`, again making `is_effective`
        false."

        Design: Difficulty/resource_temporal_overlap/certification_windows_are_closed_so_a_touching_endpoint_collides
        """
        world = _account_with_a_certification_ending_on_the_first_of_june()

        response = api_client.create_technician_certification(
            technician_certification_payload(
                world["account"]["id"],
                technician_name="Dana Ruiz",
                oem_code="WHIRLPOOL",
                cert_level="ADVANCED",
                training_completed_at="2026-06-02T00:00:00Z",
                expires_at="2027-01-01T00:00:00Z",
            ),
            WARRANTY_ADMIN,
        )
        renewal = validate_success(response, 201)
        assert renewal["cert_status"] == "ACTIVE"
        assert renewal["is_effective"] is True, (
            "2026-06-02 is at or before the clock and 2027-01-01 is at or after it"
        )

        lapsed = read_certification(world["first"]["id"])
        assert lapsed["cert_status"] == "ACTIVE", (
            "nothing has run the periodic review, so the row is still ACTIVE"
        )
        assert lapsed["is_effective"] is False, (
            "its expires_at of 2026-06-01 is behind the 2026-08-01 clock"
        )

        rows = list_certifications(servicer_account_id=world["account"]["id"])
        assert len(rows) == 2, f"Expected both certifications to persist, got {len(rows)}"

        summary = read_credit_summary(world["account"]["id"])
        assert summary["effective_cert_count"] == 1, (
            f"only the renewal is effective at the current clock, got "
            f"{summary['effective_cert_count']}"
        )
