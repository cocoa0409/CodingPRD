"""Price-schedule publishing claims: same-triple supersede, ordered publish
gauntlet (temporal before OCC), void guards, and terminal-version OCC."""
from test_helpers import (
    PRICE,
    ApiErrorId,
    assert_terminal,
    create_draft_schedule,
    create_product,
    create_terminal,
    get_terminal,
    publish_schedule,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSameTripleSupersede:
    def test_second_publish_supersedes_first(self, api):
        """PRD §3.3: "On success the schedule transitions `DRAFT` →
        `PUBLISHED`, its `published_at` is stamped once and is immutable
        thereafter, any other `PUBLISHED` schedule for the same terminal,
        product, and effective date cascades to `SUPERSEDED`, and the
        terminal's `version` increments with its `updated_at` refreshed."

        Design: Difficulty/resource_temporal_overlap/price_schedule_publish_supersedes_prior_same_triple
        """
        set_clock()
        terminal = create_terminal()
        product = create_product()

        ps1 = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=280,
        )
        publish_schedule(ps1["id"], terminal["version"])

        ps2 = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=285,
        )
        v1 = get_terminal(terminal["id"])["version"]
        publish_schedule(ps2["id"], v1)

        first = validate_success(api.get_price_schedule(ps1["id"], PRICE))
        second = validate_success(api.get_price_schedule(ps2["id"], PRICE))
        assert first["status"] == "SUPERSEDED", (
            f"prior PUBLISHED must cascade to SUPERSEDED, got {first['status']}"
        )
        assert second["status"] == "PUBLISHED"

    def test_exactly_one_published_per_triple(self, api):
        """PRD §3.3: "At most one schedule is ever `PUBLISHED` for a given
        terminal, product, and effective date."

        Design: Difficulty/resource_temporal_overlap/price_schedule_publish_supersedes_prior_same_triple
        """
        set_clock()
        terminal = create_terminal()
        product = create_product()

        ps1 = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=280,
        )
        publish_schedule(ps1["id"], terminal["version"])
        ps2 = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=285,
        )
        publish_schedule(ps2["id"], get_terminal(terminal["id"])["version"])

        rows, meta = validate_paginated(
            api.list_price_schedules(
                PRICE,
                params={
                    "terminal_id": terminal["id"],
                    "product_id": product["id"],
                    "effective_date": "2026-08-01",
                    "status": "PUBLISHED",
                },
            )
        )
        assert len(rows) == 1, (
            f"exactly one PUBLISHED schedule per triple, got {len(rows)}"
        )
        assert rows[0]["id"] == ps2["id"]
        assert rows[0]["posted_rack_cents_per_gal"] == 285


class TestPublishCheckOrdering:
    def test_past_date_beats_stale_version(self, api):
        """PRD §3.3: "Publishing is the consequential act, and its checks run
        in a fixed order. The schedule must currently be `DRAFT`, else
        `ERR_SCHEDULE_NOT_DRAFT` (HTTP 409). Its `effective_date` must not be
        earlier than the logical clock's current date, else
        `ERR_SCHEDULE_DATE_IN_PAST` (HTTP 422). The
        `posted_rack_cents_per_gal` must be greater than zero, else
        `ERR_INVALID_PRICE` (HTTP 422). Finally the optimistic concurrency
        guard of §2.7 runs: the body's `expected_terminal_version` must equal
        the terminal's current `version`, else `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_publish
        """
        set_clock()
        terminal = create_terminal()
        product = create_product()

        # Move the terminal's version forward with one legitimate publish.
        ps_a = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=280,
        )
        publish_schedule(ps_a["id"], terminal["version"])

        # DRAFT with a past effective_date; t0 version is now stale too.
        ps_past = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-07-01", posted_rack_cents_per_gal=300,
        )
        resp = api.publish_price_schedule(
            ps_past["id"],
            {"expected_terminal_version": terminal["version"]},
            PRICE,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_DATE_IN_PAST, 422)

    def test_stale_version_fires_when_date_valid(self, api):
        """PRD §3.3: "Finally the optimistic concurrency guard of §2.7 runs:
        the body's `expected_terminal_version` must equal the terminal's
        current `version`, else `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_temporal_on_publish
        """
        set_clock()
        terminal = create_terminal()
        product = create_product()

        ps_a = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-01", posted_rack_cents_per_gal=280,
        )
        publish_schedule(ps_a["id"], terminal["version"])

        ps_b = create_draft_schedule(
            terminal["id"], product["id"],
            effective_date="2026-08-02", posted_rack_cents_per_gal=285,
        )
        # terminal["version"] is stale now (publish incremented it).
        resp = api.publish_price_schedule(
            ps_b["id"],
            {"expected_terminal_version": terminal["version"]},
            PRICE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_void_on_published_schedule_rejected(api):
    """PRD §3.3: "A schedule the analyst decides not to use may be voided
    while still `DRAFT` (`ERR_SCHEDULE_NOT_DRAFT` otherwise), moving it
    `DRAFT` → `VOIDED`; both `SUPERSEDED` and `VOIDED` are terminal."

    Design: Corner/errors/error_schedule_not_draft_on_void
    """
    set_clock()
    terminal = create_terminal()
    product = create_product()
    schedule = create_draft_schedule(
        terminal["id"], product["id"],
        effective_date="2026-08-01", posted_rack_cents_per_gal=280,
    )
    publish_schedule(schedule["id"], terminal["version"])

    resp = api.void_price_schedule(schedule["id"], PRICE)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_DRAFT, 409)


def test_stale_expected_terminal_version_rejected(api):
    """PRD §2.7: "If the value does not equal the Terminal's current
    `version` — for example because another writer has since published a
    competing schedule for the same terminal, product, and date, or a
    competing notice for the same terminal and date, each of which
    legitimately increments the terminal's version — the request is rejected
    with `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."

    Design: Corner/errors/error_stale_version_on_occ_publish
    """
    set_clock()
    terminal = create_terminal()
    product = create_product()

    ps1 = create_draft_schedule(
        terminal["id"], product["id"],
        effective_date="2026-08-01", posted_rack_cents_per_gal=280,
    )
    publish_schedule(ps1["id"], terminal["version"])

    ps2 = create_draft_schedule(
        terminal["id"], product["id"],
        effective_date="2026-08-02", posted_rack_cents_per_gal=285,
    )
    resp = api.publish_price_schedule(
        ps2["id"], {"expected_terminal_version": terminal["version"]}, PRICE,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

    after = get_terminal(terminal["id"])
    assert after["version"] != terminal["version"]
    assert validate_success(api.get_price_schedule(ps2["id"], PRICE))["status"] == "DRAFT", (
        "a rejected publish must mutate nothing"
    )


def test_terminal_version_increments_on_publish(api):
    """PRD §3.3: "the terminal's `version` increments with its `updated_at`
    refreshed."
    PRD §2.5: "`version` (integer): a system-managed integer that increments
    with every mutation, including mutations driven by cascading side
    effects."

    Design: Corner/cross_cutting_layers/optimistic_concurrency_terminal_version_increments_on_each_publish
    """
    set_clock()
    terminal = create_terminal()
    product = create_product()
    before = get_terminal(terminal["id"])
    assert_terminal(before)

    schedule = create_draft_schedule(
        terminal["id"], product["id"],
        effective_date="2026-08-01", posted_rack_cents_per_gal=280,
    )
    publish_schedule(schedule["id"], before["version"])

    after = get_terminal(terminal["id"])
    assert after["version"] == before["version"] + 1, (
        f"terminal version must increment by exactly 1 on publish: "
        f"{before['version']} -> {after['version']}"
    )
