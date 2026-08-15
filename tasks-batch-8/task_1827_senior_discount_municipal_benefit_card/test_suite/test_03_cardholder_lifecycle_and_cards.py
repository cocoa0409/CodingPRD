"""The annual recertification cycle, lapse cascade, card expiry, replacement
and renewal issuance, the issuance concurrency guard, and revocation
(PRD §3.3–§3.4, §2.4, §2.7)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_benefit_card,
    assert_cardholder,
    make_cardholder_headers,
    onboard_cardholder,
    read_cards,
    read_cardholder,
    set_clock,
    submit_and_approve_recertification,
    validate_error,
    validate_success,
)


def test_recertification_window_opens_at_sixty_days(api):
    """PRD §3.3: "The member's `recertification_due_date` is set to the
    approval clock date plus 365 days."
    PRD §3.3: "When the clock reaches sixty days before a member's
    `recertification_due_date`, the member moves automatically from `ACTIVE`
    to `RECERTIFICATION_DUE`, opening the window in which a recertification
    application will be accepted."
    Onboarded at the 2026-08-01 clock, the due date is 2027-08-01 and the
    window opens at 2027-06-02.

    Design: Difficulty/non_linear_state_machine/cardholder_recertification_cycle
    """
    onboard = onboard_cardholder(full_name="Reena Cert",
                                 date_of_birth="1961-08-01",
                                 annual_income_cents=1000000,
                                 residency_address="7 Walnut St")
    ch_id = onboard["cardholder"]["id"]
    assert onboard["cardholder"]["status"] == "ACTIVE"
    assert onboard["cardholder"]["recertification_due_date"] == "2027-08-01"

    set_clock("2027-06-02T00:00:00Z")
    due = read_cardholder(ch_id)
    assert due["status"] == "RECERTIFICATION_DUE", (
        "the clock reaching due_date - 60 days opens the recertification window")


def test_recertification_approval_restores_active(api):
    """PRD §3.3: "Approval of a recertification application restores the
    member from either `RECERTIFICATION_DUE` or `LAPSED` back to `ACTIVE`,
    pushes `recertification_due_date` to the approval clock date plus 365
    days, and refreshes `annual_income_cents` and `residency_address` from the
    newly approved application."
    Approved at clock 2027-06-02, the new due date is 2028-06-01 — the cycle
    closes back to ACTIVE.

    Design: Difficulty/non_linear_state_machine/cardholder_recertification_cycle
    """
    onboard = onboard_cardholder(full_name="Reena Cert",
                                 date_of_birth="1961-08-01",
                                 annual_income_cents=1000000,
                                 residency_address="7 Walnut St")
    ch_id = onboard["cardholder"]["id"]
    set_clock("2027-06-02T00:00:00Z")
    assert read_cardholder(ch_id)["status"] == "RECERTIFICATION_DUE"

    submit_and_approve_recertification(
        ch_id, annual_income_cents=1500000, full_name="Reena Cert",
        date_of_birth="1961-08-01", residency_address="7 Walnut St")

    after = read_cardholder(ch_id)
    assert after["status"] == "ACTIVE", "recertification approval closes the cycle"
    assert after["recertification_due_date"] == "2028-06-01", (
        "approval clock date 2027-06-02 plus 365 days")
    assert after["annual_income_cents"] == 1500000, (
        "income is refreshed from the approved recertification application")


def test_recert_window_boundary_is_exact(api):
    """PRD §2.4: "Setting the clock applies every time-based transition that
    has become due, in dependency order: first the opening of recertification
    windows (a cardholder moves from `ACTIVE` to `RECERTIFICATION_DUE` once
    the clock reaches sixty days before their `recertification_due_date`),
    then lapse (a cardholder still in `RECERTIFICATION_DUE` moves to `LAPSED`
    once the clock reaches one day past the due date, and the lapse cascades
    their cards to `EXPIRED`), then card expiry (any card whose `expires_at`
    the clock has reached becomes `EXPIRED`), and finally offer retirement
    (any offer whose `valid_until` the clock date has reached becomes
    `RETIRED`)."
    One second before the boundary the member is still ACTIVE; at the boundary
    the window opens.

    Design: Corner/cross_cutting_complexity_layers/recert_window_opens_exactly_sixty_days_prior
    """
    onboard = onboard_cardholder(full_name="Window Will",
                                 residency_address="62 Window Way")
    ch_id = onboard["cardholder"]["id"]

    set_clock("2027-06-01T23:59:59Z")
    assert read_cardholder(ch_id)["status"] == "ACTIVE", (
        "one second before due_date - 60 days the window has not opened")

    set_clock("2027-06-02T00:00:00Z")
    assert read_cardholder(ch_id)["status"] == "RECERTIFICATION_DUE", (
        "the boundary is inclusive: at exactly due_date - 60 days the window opens")


def test_clock_lapse_cascades_cards_to_expired(api):
    """PRD §3.3: "If the window closes without an approval — the clock
    reaching one day past the due date — the member lapses to
    `RECERTIFICATION_DUE` → `LAPSED`, and the lapse cascades: every card of
    the member in `ACTIVE` or `SUSPENDED` status becomes `EXPIRED`, each such
    card mutation bumping the card's `version` and refreshing its
    `updated_at`."

    Design: Corner/state_machines/clock_lapse_cascades_cards_to_expired
    """
    onboard = onboard_cardholder(full_name="Lapsed Larry",
                                 residency_address="34 Late Ln")
    ch_id = onboard["cardholder"]["id"]
    card_id = onboard["card"]["id"]

    set_clock("2027-08-02T00:00:00Z")  # one day past the 2027-08-01 due date
    cardholder = read_cardholder(ch_id)
    assert cardholder["status"] == "LAPSED", (
        "window opening and lapse are both applied, in dependency order, by "
        "the single clock-set")
    cards = read_cards(ch_id)
    card = [c for c in cards if c["id"] == card_id][0]
    assert card["status"] == "EXPIRED", "the lapse cascade expires the active card"


def test_card_expires_then_renewal_issues_fresh_card(api):
    """PRD §3.4: "Independently of issuance, any card — `ACTIVE` or
    `SUSPENDED` — becomes `EXPIRED` once the clock reaches its `expires_at`,
    and the full replacement lineage of a member's cards remains visible
    through the card collection in all statuses."
    PRD §3.4: "A `RENEWAL` applies when the member holds no `ACTIVE` or
    `SUSPENDED` card at all but does hold at least one `EXPIRED` card; the new
    card's `replaces_card_id` points to the member's most recently created
    `EXPIRED` card purely as audit lineage, and any prior `EXPIRED` cards keep
    their status untouched. In both cases the new card is minted `ACTIVE` with
    a fresh sixteen-digit `card_number`, `issued_at` at the clock, and
    `expires_at` two calendar years out."

    Design: Corner/state_machines/card_expires_at_expires_at_then_renewal_issues_fresh_card
    """
    onboard = onboard_cardholder(full_name="Renew Rita",
                                 residency_address="35 Renew Rd")
    ch_id = onboard["cardholder"]["id"]
    c1_id = onboard["card"]["id"]

    # Keep the member in good standing across the card's own expiry:
    # recertification #1 at 2027-06-02 pushes the due date to 2028-06-01.
    set_clock("2027-06-02T00:00:00Z")
    submit_and_approve_recertification(ch_id, annual_income_cents=500000,
                                       full_name="Renew Rita",
                                       residency_address="35 Renew Rd")
    # Recertification #2 at 2028-04-02 (window opens 2028-06-01 - 60 days)
    # pushes the due date to 2029-04-02.
    set_clock("2028-04-02T00:00:00Z")
    assert read_cardholder(ch_id)["status"] == "RECERTIFICATION_DUE"
    submit_and_approve_recertification(ch_id, annual_income_cents=500000,
                                       full_name="Renew Rita",
                                       residency_address="35 Renew Rd")

    # The initial card's own expires_at (2028-08-01, two calendar years after
    # issuance) arrives while the member stands ACTIVE.
    set_clock("2028-08-01T00:00:00Z")
    cardholder = read_cardholder(ch_id)
    assert cardholder["status"] == "ACTIVE", (
        "due 2029-04-02 — the card expiry is not a lapse cascade")
    cards = read_cards(ch_id)
    c1 = [c for c in cards if c["id"] == c1_id][0]
    assert c1["status"] == "EXPIRED", "clock reached the card's expires_at"

    renewed = validate_success(
        api.issue_card(ch_id, "RENEWAL", cardholder["version"],
                       make_cardholder_headers(ch_id)), 201)
    assert_benefit_card(renewed)
    assert renewed["status"] == "ACTIVE"
    assert renewed["issue_reason"] == "RENEWAL"
    assert renewed["replaces_card_id"] == c1_id, (
        "renewal records the most recently created EXPIRED card as audit lineage")
    assert renewed["expires_at"].startswith("2030-08-01T00:00:00"), (
        "expires_at is two calendar years after the 2028-08-01 issuance")

    cards_after = read_cards(ch_id)
    active_cards = [c for c in cards_after if c["status"] == "ACTIVE"]
    assert len(active_cards) == 1, "exactly one ACTIVE card exists after renewal"
    assert active_cards[0]["id"] == renewed["id"]


def test_renewal_rejected_while_card_active(api):
    """PRD §3.4: "The two reasons serve disjoint situations, and requesting
    one when its precondition does not hold is rejected with
    `ERR_REPLACEMENT_NOT_ALLOWED` (HTTP 409). A `REPLACEMENT` requires the
    member to currently hold a card in `ACTIVE` or `SUSPENDED` status;
    issuance supersedes that card, moving it to `REPLACED` — whether it was
    `ACTIVE` or `SUSPENDED` — and recording the superseded card's identifier
    in the new card's `replaces_card_id`. A `RENEWAL` applies when the member
    holds no `ACTIVE` or `SUSPENDED` card at all but does hold at least one
    `EXPIRED` card; the new card's `replaces_card_id` points to the member's
    most recently created `EXPIRED` card purely as audit lineage, and any
    prior `EXPIRED` cards keep their status untouched."

    Design: Corner/validations/renewal_rejected_while_card_active
    """
    onboard = onboard_cardholder(full_name="Renew Early",
                                 residency_address="49 Card Ct")
    ch_id = onboard["cardholder"]["id"]
    assert onboard["card"]["status"] == "ACTIVE"
    res = api.issue_card(ch_id, "RENEWAL", onboard["cardholder"]["version"],
                         make_cardholder_headers(ch_id))
    validate_error(res, ApiErrorId.ERR_REPLACEMENT_NOT_ALLOWED)


def test_replacement_supersedes_and_conserves_active_count(api,
                                                           program_administrator_headers):
    """PRD §3.4: "A `REPLACEMENT` requires the member to currently hold a card
    in `ACTIVE` or `SUSPENDED` status; issuance supersedes that card, moving
    it to `REPLACED` — whether it was `ACTIVE` or `SUSPENDED` — and recording
    the superseded card's identifier in the new card's `replaces_card_id`."
    The pair (mint ACTIVE successor, supersede the prior card) conserves the
    count of ACTIVE cards at exactly one.

    Design: Difficulty/compensating_invariant/replacement_conserves_active_card_count
    """
    onboard = onboard_cardholder(full_name="Riley Replace",
                                 residency_address="17 Swap St")
    ch_id = onboard["cardholder"]["id"]
    c1_id = onboard["card"]["id"]
    assert onboard["card"]["status"] == "ACTIVE"

    c2 = validate_success(
        api.issue_card(ch_id, "REPLACEMENT", onboard["cardholder"]["version"],
                       program_administrator_headers), 201)
    assert_benefit_card(c2)
    assert c2["status"] == "ACTIVE"
    assert c2["issue_reason"] == "REPLACEMENT"
    assert c2["replaces_card_id"] == c1_id

    cards = read_cards(ch_id)
    c1 = [c for c in cards if c["id"] == c1_id][0]
    assert c1["status"] == "REPLACED", "the superseded card moves to REPLACED"
    active_cards = [c for c in cards if c["status"] == "ACTIVE"]
    assert len(active_cards) == 1 and active_cards[0]["id"] == c2["id"], (
        "invariant: exactly one ACTIVE card before and after the replacement pair")


def test_replacement_increments_cardholder_version(api, program_administrator_headers):
    """PRD §3.4: "Issuance requires the member to stand in `ACTIVE` or
    `RECERTIFICATION_DUE` — a `SUSPENDED`, `LAPSED`, or `REVOKED` member is
    rejected with `ERR_CARDHOLDER_NOT_ACTIVE` (HTTP 409) — and every
    successful issuance increments the cardholder's `version` by one."

    Design: Difficulty/compensating_invariant/replacement_conserves_active_card_count
    """
    onboard = onboard_cardholder(full_name="Riley Version",
                                 residency_address="17 Swap St")
    ch_id = onboard["cardholder"]["id"]
    version_before = onboard["cardholder"]["version"]

    validate_success(
        api.issue_card(ch_id, "REPLACEMENT", version_before,
                       program_administrator_headers), 201)

    after = read_cardholder(ch_id)
    assert after["version"] == version_before + 1, (
        "issuance increments the cardholder version by exactly one")


def test_stale_cardholder_version_rejected(api, program_administrator_headers):
    """PRD §2.7: "If the supplied value does not match the cardholder's
    current `version` — because some other write has advanced the cardholder's
    version since the client last read it — the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no card is minted."
    A first replacement succeeds and advances the version by one; replaying
    the same observed version is now stale.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_rejected_and_success_advances
    """
    onboard = onboard_cardholder(full_name="Occ Olga",
                                 residency_address="61 Version Ct")
    ch_id = onboard["cardholder"]["id"]
    observed_version = onboard["cardholder"]["version"]

    first = validate_success(
        api.issue_card(ch_id, "REPLACEMENT", observed_version,
                       program_administrator_headers), 201)
    assert first["status"] == "ACTIVE", "the first replacement mints a card"
    advanced = read_cardholder(ch_id)
    assert advanced["version"] == observed_version + 1

    res = api.issue_card(ch_id, "REPLACEMENT", observed_version,
                         program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_revoke_already_revoked_rejected(api, fraud_analyst_headers):
    """PRD §3.3: "Revoking an already `REVOKED` member is rejected with
    `ERR_CARDHOLDER_ALREADY_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/revoke_already_revoked_cardholder_rejected
    """
    onboard = onboard_cardholder(full_name="Double Revoke",
                                 residency_address="31 End St")
    ch_id = onboard["cardholder"]["id"]
    revoked = validate_success(
        api.revoke_cardholder(ch_id, "fraud confirmed", fraud_analyst_headers), 200)
    assert revoked["status"] == "REVOKED"

    res = api.revoke_cardholder(ch_id, "again", fraud_analyst_headers)
    validate_error(res, ApiErrorId.ERR_CARDHOLDER_ALREADY_TERMINAL)


def test_cardholder_not_found_returns_404(api, program_administrator_headers):
    """PRD §2.8: "The not-found family comprises `ERR_APPLICATION_NOT_FOUND`,
    `ERR_DOCUMENT_NOT_FOUND`, `ERR_CARDHOLDER_NOT_FOUND`, `ERR_CARD_NOT_FOUND`,
    `ERR_MERCHANT_NOT_FOUND`, `ERR_TRANSACTION_NOT_FOUND`,
    `ERR_CLAIM_NOT_FOUND`, and `ERR_FUND_NOT_FOUND`."

    Design: Corner/entities/cardholder_not_found_returns_404
    """
    set_clock("2026-08-01T00:00:00Z")
    res = api.get_cardholder(NON_EXISTENT_UUID, program_administrator_headers)
    validate_error(res, ApiErrorId.ERR_CARDHOLDER_NOT_FOUND)


def test_age_years_reflects_logical_clock(api, program_administrator_headers):
    """PRD §3.3: "The cardholder record also surfaces derived figures on every
    read: `age_years`, the whole-year age against the current clock date;
    `fraud_flag_count`, the number of the member's transactions currently in
    `FLAGGED` status; `ytd_discount_cents`, the sum of `discount_cents` over
    the member's transactions in `POSTED` or `FLAGGED` status whose
    `created_at` falls inside the clock's current calendar year; and
    `ytd_transaction_count`, the count of that same inclusion set."
    Born 1960-06-15, the member's 66th birthday (2026-06-15) has passed at the
    2026-08-01 clock.

    Design: Corner/entities/computed_age_years_reflects_logical_clock
    """
    onboard = onboard_cardholder(full_name="Age Computed",
                                 date_of_birth="1960-06-15",
                                 residency_address="24 Years Way")
    cardholder = validate_success(
        api.get_cardholder(onboard["cardholder"]["id"],
                           program_administrator_headers), 200)
    assert_cardholder(cardholder)
    assert cardholder["age_years"] == 66
