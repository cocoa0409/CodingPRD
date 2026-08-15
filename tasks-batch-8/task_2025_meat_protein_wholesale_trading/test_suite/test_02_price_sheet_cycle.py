"""Weekly price sheet cycle: publication gates, half-open week conflicts,
the supersede cascade, and the fixed startup clock."""
from test_helpers import (
    WEEK_1,
    WEEK_2,
    ApiErrorId,
    add_sheet_line,
    api_client,
    create_customer,
    create_product,
    create_sheet,
    get_allocation,
    get_customer,
    get_sheet,
    make_customer_rep_headers,
    publish_sheet,
    request_allocation,
    run_sheet,
    validate_error,
    validate_success,
)


class TestPublishSupersedeCascade:
    """Three-link cascade: publish S2 superseding S1 -> S1 SUPERSEDED -> S1's
    shipment-free allocations CANCELLED -> customer exposure recomputed and the
    credit hold auto-released."""

    def _setup(self):
        product = create_product(product_code="RIBEYE-C", max_fat_pct=12.0)
        customer = create_customer(customer_code="CUST-C",
                                   credit_limit_cents=350_000,
                                   allocation_tier="TIER_1")
        s1 = create_sheet(WEEK_1)
        line = add_sheet_line(s1["id"], product["id"], 700, 100_000)
        publish_sheet(s1["id"])
        rep = make_customer_rep_headers(customer["id"])
        a1 = request_allocation(customer, line["id"], 500)
        run_sheet(s1["id"])
        a2 = request_allocation(customer, line["id"], 100)
        run_sheet(s1["id"])
        held = get_customer(customer["id"])
        assert held["status"] == "CREDIT_HOLD", (
            f"Setup failed: exposure 420000 > limit 350000 must hold the "
            f"customer, got {held['status']}"
        )
        s2 = create_sheet(WEEK_2, supersedes_sheet_id=s1["id"])
        add_sheet_line(s2["id"], product["id"], 720, 100_000)
        return product, customer, s1, s2, line, a1, a2

    def test_publish_supersedes_sheet_and_cancels_its_allocations(
            self, desk_admin_headers):
        """PRD §3.2: "First, the referenced sheet transitions from `PUBLISHED`
        to `SUPERSEDED`. Second, every still-`REQUESTED` allocation on the
        superseded sheet's lines, and every `CONFIRMED` allocation on those
        lines that has no shipment in `STAGING` or `IN_TRANSIT`, is cancelled
        with `cancel_reason` `SHEET_SUPERSEDED`."

        Design: Difficulty/transitive_cascade/publish_supersede_cascade_releases_credit_hold
        """
        _, _, s1, s2, _, a1, a2 = self._setup()

        resp = api_client.publish_price_sheet(s2["id"], desk_admin_headers)
        validate_success(resp)

        s1_after = get_sheet(s1["id"])
        assert s1_after["status"] == "SUPERSEDED", \
            f"link 1: superseded sheet must move to SUPERSEDED, got {s1_after['status']}"
        for alloc_id, label in ((a1["id"], "A1"), (a2["id"], "A2")):
            alloc = get_allocation(alloc_id)
            assert alloc["status"] == "CANCELLED", \
                f"link 2: {label} must be CANCELLED, got {alloc['status']}"
            assert alloc["cancel_reason"] == "SHEET_SUPERSEDED", \
                f"link 2: {label} cancel_reason must be SHEET_SUPERSEDED, " \
                f"got {alloc['cancel_reason']}"

    def test_publish_supersede_cascade_releases_credit_hold(
            self, desk_admin_headers):
        """PRD §3.2: "Third, each of those cancellations recomputes the
        affected customer's `outstanding_exposure_cents` and re-evaluates the
        automatic credit-hold release of §2.10."
        PRD §2.10: "a customer on `CREDIT_HOLD` whose exposure falls to the
        limit or below transitions back to `ACTIVE`."

        Design: Difficulty/transitive_cascade/publish_supersede_cascade_releases_credit_hold
        """
        _, customer, _, s2, _, _, _ = self._setup()

        resp = api_client.publish_price_sheet(s2["id"], desk_admin_headers)
        validate_success(resp)

        after = get_customer(customer["id"])
        assert after["outstanding_exposure_cents"] == 0, (
            f"link 3: cancelling both allocations must drop exposure to 0, "
            f"got {after['outstanding_exposure_cents']}"
        )
        assert after["status"] == "ACTIVE", (
            f"link 3: exposure at or below the limit auto-releases the hold, "
            f"got {after['status']}"
        )


class TestSheetWeekOverlap:
    def _setup_s1(self):
        product = create_product(product_code="RIBEYE-J", max_fat_pct=12.0)
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], product["id"], 700, 10_000)
        publish_sheet(s1["id"])
        return product, s1

    def test_same_week_publish_conflicts(self, desk_admin_headers):
        """PRD §3.2: "No other sheet in `DRAFT` or `PUBLISHED` status may cover
        the same `week_start_date`, else `ERR_PRICE_SHEET_WEEK_CONFLICT`."
        PRD §2.7: "each names the half-open week that runs from that Monday up
        to but not including the following Monday."

        Design: Difficulty/resource_temporal_overlap/price_sheet_week_half_open_overlap
        """
        product, s1 = self._setup_s1()
        s2 = create_sheet(WEEK_1)  # same week as PUBLISHED S1
        add_sheet_line(s2["id"], product["id"], 701, 10_000)

        resp = api_client.publish_price_sheet(s2["id"], desk_admin_headers)
        validate_error(resp, ApiErrorId.ERR_PRICE_SHEET_WEEK_CONFLICT)
        assert get_sheet(s2["id"])["status"] == "DRAFT", \
            "a conflicting publish must leave the challenger DRAFT"

    def test_adjacent_week_publish_is_not_a_conflict(self, desk_admin_headers):
        """PRD §2.7: "A price sheet's `week_start_date` and a forward
        contract's `delivery_week_start` are each the ISO date of a Monday,
        and each names the half-open week that runs from that Monday up to but
        not including the following Monday."
        PRD §3.2: "First, the referenced sheet transitions from `PUBLISHED` to
        `SUPERSEDED`."

        Design: Difficulty/resource_temporal_overlap/price_sheet_week_half_open_overlap
        """
        product, s1 = self._setup_s1()
        s3 = create_sheet(WEEK_2, supersedes_sheet_id=s1["id"])
        add_sheet_line(s3["id"], product["id"], 702, 10_000)

        resp = api_client.publish_price_sheet(s3["id"], desk_admin_headers)
        data = validate_success(resp)
        assert data["status"] == "PUBLISHED", (
            f"the immediately adjacent week is permitted because the interval "
            f"is half-open, got {data['status']}"
        )
        assert get_sheet(s1["id"])["status"] == "SUPERSEDED", \
            "publishing the superseding sheet must move S1 to SUPERSEDED"


class TestSheetGates:
    def test_line_add_to_published_sheet_returns_409(self, trader_headers,
                                                     desk_admin_headers):
        """PRD §3.2: "Adding a line to a sheet that is not `DRAFT` is rejected
        with `ERR_PRICE_SHEET_NOT_DRAFT`."

        Design: Corner/validations/line_add_to_published_sheet_returns_409
        """
        product = create_product(product_code="RIBEYE-LF", max_fat_pct=12.0)
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], product["id"], 700, 10_000)
        publish_sheet(s1["id"])

        resp = api_client.add_sheet_line(
            s1["id"],
            {"product_id": product["id"], "price_per_lb_cents": 701,
             "weekly_supply_lbs": 500},
            trader_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRICE_SHEET_NOT_DRAFT)
        assert get_sheet(s1["id"])["status"] == "PUBLISHED"

    def test_publish_without_lines_returns_409(self, desk_admin_headers):
        """PRD §3.2: "It must carry at least one line, else
        `ERR_SHEET_HAS_NO_LINES`."

        Design: Corner/validations/publish_without_lines_returns_409
        """
        product = create_product(product_code="RIBEYE-NL", max_fat_pct=12.0)
        s1 = create_sheet(WEEK_1)

        resp = api_client.publish_price_sheet(s1["id"], desk_admin_headers)
        validate_error(resp, ApiErrorId.ERR_SHEET_HAS_NO_LINES)

        add_sheet_line(s1["id"], product["id"], 700, 10_000)
        ok = api_client.publish_price_sheet(s1["id"], desk_admin_headers)
        assert validate_success(ok)["status"] == "PUBLISHED"

    def test_sheet_week_must_be_monday(self, trader_headers):
        """PRD §2.7: "A date value that is not a Monday is rejected with
        `ERR_INVALID_WEEK_START` (HTTP 422)."
        PRD §3.2: "The sheet is born in `DRAFT` status with `published_at`
        null."

        Design: Corner/validations/sheet_week_must_be_monday
        """
        bad = api_client.create_price_sheet({"week_start_date": "2026-08-04"},
                                            trader_headers)
        validate_error(bad, ApiErrorId.ERR_INVALID_WEEK_START)

        ok = api_client.create_price_sheet({"week_start_date": "2026-08-10"},
                                           trader_headers)
        assert validate_success(ok, expected_status=201)["status"] == "DRAFT"


class TestLogicalClockDefault:
    def test_clock_default_is_fixed_startup_time(self, desk_admin_headers):
        """PRD §2.4: "Before any operator advances it, the clock reads exactly
        `2026-08-01T00:00:00Z`, and it never falls back to wall-clock time."
        PRD §3.2: "On successful publication the sheet's `published_at` is
        stamped from the logical clock"

        Design: Corner/cross_cutting/clock_default_is_fixed_startup_time
        """
        product = create_product(product_code="RIBEYE-CK", max_fat_pct=12.0)
        s1 = create_sheet(WEEK_1)
        add_sheet_line(s1["id"], product["id"], 700, 10_000)

        resp = api_client.publish_price_sheet(s1["id"], desk_admin_headers)
        data = validate_success(resp)
        published_at = data["published_at"]
        assert isinstance(published_at, str) and published_at.startswith(
            "2026-08-01T00:00:00"), (
            f"publication must be stamped from the fixed startup clock "
            f"2026-08-01T00:00:00Z, got {published_at}"
        )
