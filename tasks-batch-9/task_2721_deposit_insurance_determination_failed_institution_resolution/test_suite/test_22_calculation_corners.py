"""Arithmetic corners of the resolution: the points where a division becomes a whole number.

Every figure asserted here is re-derived from the formula, the rounding discipline
and the evaluation order the PRD pins for that one computation — the readiness
score and variance gates, the five ownership-category buckets and their limits,
the floor-plus-remainder uninsured hold allocation, the liquidation baseline, the
nine priced steps of a bid, the two dividend classes, and the running receivership
cash identity.  Money is always an integer count of cents and every rate an
integer count of basis points.
"""
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.assertions import (
    assert_account_dimensions,
    assert_bid_costs,
    assert_breakdown_categories,
    assert_category_breakdown,
    assert_certificate,
    assert_cents,
    assert_conservation_identities_hold,
    assert_determination_amounts,
    assert_fields_equal,
    assert_institution_aggregates,
    assert_submission_scored,
    assert_summary,
)


# ---------------------------------------------------------------------------
# Readiness standardization: the score floor and the variance ceiling
# ---------------------------------------------------------------------------
def test_readiness_gate_boundaries_score_9800_and_variance_25_both_pass(client):
    """A package landing exactly on both readiness gates standardizes, while one cent
    more of reported variance rejects it, showing both comparisons are inclusive.

    PRD: "A score of exactly 9800 clears the floor, and a variance of exactly 25 clears the ceiling."

    Design: Corner/calculations/readiness_gate_boundaries_score_9800_and_variance_25_both_pass
    """
    X.open_at_setup_clock(client)

    # 98 of 100 records parse cleanly, and 1002500 reported against 1000000 booked
    # is a variance of exactly 25 basis points.
    passing = X.new_institution(
        client,
        cert_number="61023",
        legal_name="Boundary Pass Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    passing_depositor = X.new_depositor(
        client, passing["id"], tin_hash="TIN-BP-1", legal_name="Omar Haddad"
    )
    X.new_account(
        client,
        passing["id"],
        passing_depositor["id"],
        account_number="BP-0001",
        ownership_category="SINGLE",
        balance_cents=1000000,
        accrued_interest_cents=0,
    )
    passing_submission = X.file_readiness(
        client,
        passing["id"],
        file_format="VENDOR_CSV",
        record_count=100,
        malformed_record_count=2,
        reported_deposit_total_cents=1002500,
    )

    # The same package reporting 1002600 gives a variance of 26 basis points.
    failing = X.new_institution(
        client,
        cert_number="61024",
        legal_name="Boundary Fail Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    failing_depositor = X.new_depositor(
        client, failing["id"], tin_hash="TIN-BP-2", legal_name="Pia Lindqvist"
    )
    X.new_account(
        client,
        failing["id"],
        failing_depositor["id"],
        account_number="BP-0002",
        ownership_category="SINGLE",
        balance_cents=1000000,
        accrued_interest_cents=0,
    )
    failing_submission = X.file_readiness(
        client,
        failing["id"],
        file_format="VENDOR_CSV",
        record_count=100,
        malformed_record_count=2,
        reported_deposit_total_cents=1002600,
    )

    standardized = X.standardize(client, passing_submission["id"])
    assert_submission_scored(
        standardized,
        "STANDARDIZED",
        C.READINESS_SCORE_FLOOR_BPS,
        C.READINESS_VARIANCE_CEILING_BPS,
        None,
    )

    rejected = X.standardize(client, failing_submission["id"])
    assert_submission_scored(
        rejected,
        "REJECTED",
        C.READINESS_SCORE_FLOOR_BPS,
        C.READINESS_VARIANCE_CEILING_BPS + 1,
        "TOTAL_VARIANCE_EXCEEDED",
    )

    # Only the standardized package earns the institution its readiness attestation.
    assert_fields_equal(
        X.get_institution(client, passing["id"]),
        {"status": "RESOLUTION_READY", "readiness_standardized": True},
    )
    assert_fields_equal(
        X.get_institution(client, failing["id"]),
        {"status": "READINESS_COLLECTION", "readiness_standardized": False},
    )


def test_readiness_variance_branch_when_no_accounts_are_booked(client):
    """With no deposit accounts booked, a package reporting zero standardizes on a
    variance of zero while a package reporting one cent takes the 10000 sentinel.

    PRD: "When the booked total is zero, `deposit_total_variance_bps` is zero if `reported_deposit_total_cents` is also zero and 10000 otherwise."

    Design: Corner/calculations/readiness_variance_branch_when_no_accounts_are_booked
    """
    X.open_at_setup_clock(client)

    # Five records, none malformed, so the score reads 10000 and never gates.
    reconciled = X.new_institution(
        client,
        cert_number="61025",
        legal_name="Zero Booked Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    reconciled_submission = X.file_readiness(
        client,
        reconciled["id"],
        file_format="FDIC_STANDARD_V2",
        record_count=5,
        malformed_record_count=0,
        reported_deposit_total_cents=0,
    )
    mismatched = X.new_institution(
        client,
        cert_number="61026",
        legal_name="Zero Booked Mismatch Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    mismatched_submission = X.file_readiness(
        client,
        mismatched["id"],
        file_format="FDIC_STANDARD_V2",
        record_count=5,
        malformed_record_count=0,
        reported_deposit_total_cents=1,
    )

    # The zero denominator is a declared branch, not a division by zero.
    standardized = X.standardize(client, reconciled_submission["id"])
    assert_submission_scored(standardized, "STANDARDIZED", C.BPS_WHOLE, 0, None)

    rejected = X.standardize(client, mismatched_submission["id"])
    assert_submission_scored(
        rejected, "REJECTED", C.BPS_WHOLE, C.BPS_WHOLE, "TOTAL_VARIANCE_EXCEEDED"
    )

    assert_fields_equal(
        X.get_institution(client, reconciled["id"]),
        {"status": "RESOLUTION_READY", "readiness_standardized": True},
    )
    assert_institution_aggregates(
        X.get_institution(client, reconciled["id"]),
        total_deposit_balance_cents=0,
        depositor_record_count=0,
    )


# ---------------------------------------------------------------------------
# Ownership-category attribution: the five buckets and their limits
# ---------------------------------------------------------------------------
def test_joint_share_attribution_rounds_half_up_per_share(client):
    """Each co-owner's share of a joint account is rounded half up on its own, so an
    odd balance split 3333/6667 basis points splits without creating or losing a cent.

    PRD: "the bucket receives the account's contribution multiplied by that interest's `designated_share_bps`, divided by 10000, and rounded half up to a whole cent. Rounding happens on each share, before any limit is considered."

    Design: Corner/calculations/joint_share_attribution_rounds_half_up_per_share
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61027",
        legal_name="Joint Rounding Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    quill = X.new_depositor(
        client, institution["id"], tin_hash="TIN-JR-1", legal_name="Quill Marsden"
    )
    rosa = X.new_depositor(
        client, institution["id"], tin_hash="TIN-JR-2", legal_name="Rosa Marsden"
    )
    account = X.new_account(
        client,
        institution["id"],
        quill["id"],
        account_number="JT-0001",
        ownership_category="JOINT",
        balance_cents=1000001,
        accrued_interest_cents=0,
    )
    # 1000001 * 3333 / 10000 = 333300.3333 and 1000001 * 6667 / 10000 = 666700.6667.
    X.new_interest(client, account["id"], quill["id"], "CO_OWNER", 3333)
    X.new_interest(client, account["id"], rosa["id"], "CO_OWNER", 6667)
    X.make_resolution_ready(client, institution["id"], 1000001)
    X.close_charter(client, institution["id"])

    quill_determination = X.open_determination(client, quill["id"])
    rosa_determination = X.open_determination(client, rosa["id"])

    quill_prepared = X.prepare(client, quill_determination["id"])
    rosa_prepared = X.prepare(client, rosa_determination["id"])

    assert_fields_equal(quill_prepared, {"status": "PREPARED"})
    assert_determination_amounts(quill_prepared, 333300, 0, 333300)
    assert_category_breakdown(
        quill_prepared, "JOINT", 333300, C.SMDIA_CENTS, 333300, 0
    )
    assert_breakdown_categories(quill_prepared, ["JOINT"])

    assert_determination_amounts(rosa_prepared, 666701, 0, 666701)
    assert_category_breakdown(rosa_prepared, "JOINT", 666701, C.SMDIA_CENTS, 666701, 0)

    # The two independently rounded shares reconstitute the account exactly.
    assert (
        quill_prepared["attributed_total_cents"]
        + rosa_prepared["attributed_total_cents"]
        == 1000001
    )

    assert_fields_equal(
        X.get_depositor(client, quill["id"]), {"attributed_total_cents": 333300}
    )
    assert_fields_equal(
        X.get_depositor(client, rosa["id"]), {"attributed_total_cents": 666701}
    )


def test_revocable_trust_limit_scales_with_beneficiary_count_and_caps_at_five(client):
    """A revocable trust's limit is one standard maximum per named beneficiary, capped
    at five, and a trust naming nobody still receives one standard maximum.

    PRD: "What varies is the limit, which is the standard maximum multiplied by the smaller of five and the number of distinct depositors named with `interest_role` `BENEFICIARY` on those accounts."

    Design: Corner/calculations/revocable_trust_limit_scales_with_beneficiary_count_and_caps_at_five
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61028",
        legal_name="Revocable Trust Bank",
        book_asset_value_cents=200000000,
        estimated_liquidation_recovery_cents=90000000,
    )
    sunil = X.new_depositor(
        client, institution["id"], tin_hash="TIN-RT-G1", legal_name="Sunil Rao"
    )
    tanya = X.new_depositor(
        client, institution["id"], tin_hash="TIN-RT-G2", legal_name="Tanya Cole"
    )
    beneficiaries = [
        X.new_depositor(
            client,
            institution["id"],
            tin_hash=f"TIN-RT-B{n}",
            legal_name=f"Beneficiary {n}",
        )
        for n in range(1, 7)
    ]

    # Six distinct beneficiaries on a 150000000 trust, so the multiplier truncates to five.
    sunil_account = X.new_account(
        client,
        institution["id"],
        sunil["id"],
        account_number="RT-0001",
        ownership_category="REVOCABLE_TRUST",
        balance_cents=150000000,
        accrued_interest_cents=0,
    )
    for beneficiary in beneficiaries:
        X.new_interest(
            client, sunil_account["id"], beneficiary["id"], "BENEFICIARY", 1000
        )
    # A trust naming nobody counts as one beneficiary.
    tanya_account = X.new_account(
        client,
        institution["id"],
        tanya["id"],
        account_number="RT-0002",
        ownership_category="REVOCABLE_TRUST",
        balance_cents=30000000,
        accrued_interest_cents=0,
        opened_at="2024-04-01T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], 180000000)
    X.close_charter(client, institution["id"])

    sunil_determination = X.open_determination(client, sunil["id"])
    tanya_determination = X.open_determination(client, tanya["id"])

    capped = X.prepare(client, sunil_determination["id"])
    capped_limit = C.SMDIA_CENTS * C.REVOCABLE_BENEFICIARY_CAP
    assert capped_limit == 125000000
    assert_determination_amounts(capped, capped_limit, 25000000, 150000000)
    assert_category_breakdown(
        capped, "REVOCABLE_TRUST", 150000000, capped_limit, capped_limit, 25000000
    )

    floored = X.prepare(client, tanya_determination["id"])
    assert_determination_amounts(floored, C.SMDIA_CENTS, 5000000, 30000000)
    assert_category_breakdown(
        floored,
        "REVOCABLE_TRUST",
        30000000,
        C.SMDIA_CENTS,
        C.SMDIA_CENTS,
        5000000,
    )

    # Each grantor's trust account carries its own full contribution.
    assert_fields_equal(
        X.get_account(client, sunil_account["id"]),
        {"attributed_amount_cents": 150000000},
    )
    assert_fields_equal(
        X.get_account(client, tanya_account["id"]),
        {"attributed_amount_cents": 30000000},
    )


def test_irrevocable_trust_insured_is_the_per_beneficiary_min_sum(client):
    """An irrevocable trust is insured beneficiary by beneficiary rather than against a
    single bucket limit, so two half-share beneficiaries buy two standard maximums.

    PRD: "for each `BENEFICIARY` interest on such an account, take the account's contribution multiplied by that interest's `designated_share_bps`, divided by 10000, rounded half up, then take the smaller of that share and one standard maximum; the insured figure is the sum of those per-beneficiary results."

    Design: Corner/calculations/irrevocable_trust_insured_is_the_per_beneficiary_min_sum
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61029",
        legal_name="Irrevocable Trust Bank",
        book_asset_value_cents=100000000,
        estimated_liquidation_recovery_cents=40000000,
    )
    umberto = X.new_depositor(
        client, institution["id"], tin_hash="TIN-IT-G1", legal_name="Umberto Salas"
    )
    xena = X.new_depositor(
        client, institution["id"], tin_hash="TIN-IT-G2", legal_name="Xena Boateng"
    )
    vera = X.new_depositor(
        client, institution["id"], tin_hash="TIN-IT-B1", legal_name="Vera Salas"
    )
    wes = X.new_depositor(
        client, institution["id"], tin_hash="TIN-IT-B2", legal_name="Wes Salas"
    )

    # 60000000 split 5000/5000 gives each beneficiary a 30000000 share, capped at 25000000.
    umberto_account = X.new_account(
        client,
        institution["id"],
        umberto["id"],
        account_number="IT-0001",
        ownership_category="IRREVOCABLE_TRUST",
        balance_cents=60000000,
        accrued_interest_cents=0,
    )
    X.new_interest(client, umberto_account["id"], vera["id"], "BENEFICIARY", 5000)
    X.new_interest(client, umberto_account["id"], wes["id"], "BENEFICIARY", 5000)
    # No beneficiary interests at all, so the account is insured at one standard maximum.
    X.new_account(
        client,
        institution["id"],
        xena["id"],
        account_number="IT-0002",
        ownership_category="IRREVOCABLE_TRUST",
        balance_cents=30000000,
        accrued_interest_cents=0,
        opened_at="2024-04-01T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], 90000000)
    X.close_charter(client, institution["id"])

    umberto_determination = X.open_determination(client, umberto["id"])
    xena_determination = X.open_determination(client, xena["id"])

    per_beneficiary = X.prepare(client, umberto_determination["id"])
    assert_determination_amounts(per_beneficiary, 50000000, 10000000, 60000000)
    assert_fields_equal(
        per_beneficiary["category_breakdown"]["IRREVOCABLE_TRUST"],
        {
            "attributed_cents": 60000000,
            "insured_cents": 50000000,
            "uninsured_cents": 10000000,
        },
    )

    fallback = X.prepare(client, xena_determination["id"])
    assert_determination_amounts(fallback, C.SMDIA_CENTS, 5000000, 30000000)

    # A named beneficiary holds no attribution in its own right.
    assert_fields_equal(
        X.get_depositor(client, vera["id"]), {"attributed_total_cents": 0}
    )
    assert_fields_equal(
        X.get_depositor(client, wes["id"]), {"attributed_total_cents": 0}
    )


def test_pass_through_granted_versus_denied_moves_the_single_bucket(client):
    """The recordkeeping quality of a brokered omnibus account alone decides whether the
    balance is credited to the participants or stays with the broker of record.

    PRD: "When `recordkeeping_status` is `DEFICIENT` or `PENDING`, pass-through is denied: the entire omnibus contribution lands in the broker's own single-ownership bucket and the participants are credited nothing."

    Design: Corner/calculations/pass_through_granted_versus_denied_moves_the_single_bucket
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61030",
        legal_name="Pass Through Bank",
        book_asset_value_cents=80000000,
        estimated_liquidation_recovery_cents=30000000,
    )
    broker = X.new_depositor(
        client,
        institution["id"],
        tin_hash="TIN-PT-BR",
        legal_name="Vantage Deposits LLC",
        depositor_type="BROKER",
        contact_email="ops@vantage.example.com",
    )
    yuki = X.new_depositor(
        client, institution["id"], tin_hash="TIN-PT-P1", legal_name="Yuki Tanabe"
    )
    zane = X.new_depositor(
        client, institution["id"], tin_hash="TIN-PT-P2", legal_name="Zane Okafor"
    )

    # Pass-through granted: each participant is credited half of 30000000.
    granted = X.new_account(
        client,
        institution["id"],
        broker["id"],
        account_number="BR-COMPLETE",
        ownership_category="BROKERED_PASS_THROUGH",
        balance_cents=30000000,
        accrued_interest_cents=0,
        broker_name="Vantage Deposits LLC",
        recordkeeping_status="COMPLETE",
    )
    X.new_interest(client, granted["id"], yuki["id"], "PARTICIPANT", 5000)
    X.new_interest(client, granted["id"], zane["id"], "PARTICIPANT", 5000)
    # Pass-through denied: the whole omnibus balance belongs to the broker.
    X.new_account(
        client,
        institution["id"],
        broker["id"],
        account_number="BR-DEFICIENT",
        ownership_category="BROKERED_PASS_THROUGH",
        balance_cents=30000000,
        accrued_interest_cents=0,
        opened_at="2024-04-01T00:00:00Z",
        broker_name="Vantage Deposits LLC",
        recordkeeping_status="DEFICIENT",
    )
    X.make_resolution_ready(client, institution["id"], 60000000)
    X.close_charter(client, institution["id"])

    broker_determination = X.open_determination(client, broker["id"])
    yuki_determination = X.open_determination(client, yuki["id"])

    broker_prepared = X.prepare(client, broker_determination["id"])
    assert_determination_amounts(broker_prepared, C.SMDIA_CENTS, 5000000, 30000000)
    assert_category_breakdown(
        broker_prepared, "SINGLE", 30000000, C.SMDIA_CENTS, C.SMDIA_CENTS, 5000000
    )
    # Brokered dollars always resolve into a single-ownership bucket.
    assert_breakdown_categories(broker_prepared, ["SINGLE"])

    participant_prepared = X.prepare(client, yuki_determination["id"])
    assert_determination_amounts(participant_prepared, 15000000, 0, 15000000)
    assert_category_breakdown(
        participant_prepared, "SINGLE", 15000000, C.SMDIA_CENTS, 15000000, 0
    )
    assert_breakdown_categories(participant_prepared, ["SINGLE"])


def test_determination_input_set_excludes_accounts_still_pending(client):
    """An account loaded after the charter closed never froze, so it is excluded from the
    depositor's attribution while still counting in the institution's deposit total.

    PRD: "Accounts are read at `insurance_status` `FROZEN_FOR_DETERMINATION` — the normal post-closure state — or at `DETERMINED`, which is how a re-prepare after a revision loop still sees the accounts it already determined."

    Design: Corner/calculations/determination_input_set_excludes_accounts_still_pending
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61031",
        legal_name="Late Account Bank",
        book_asset_value_cents=10000000,
        estimated_liquidation_recovery_cents=4000000,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash="TIN-LA-1", legal_name="Aurel Bianco"
    )
    frozen_account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="PF-0001",
        ownership_category="SINGLE",
        balance_cents=5000000,
        accrued_interest_cents=0,
    )
    X.make_resolution_ready(client, institution["id"], 5000000)
    X.close_charter(client, institution["id"])

    # Loaded after the closing cascade, so this account is still PENDING.
    late_account = X.new_account(
        client,
        institution["id"],
        depositor["id"],
        account_number="PF-0002",
        ownership_category="SINGLE",
        balance_cents=3000000,
        accrued_interest_cents=0,
        opened_at="2024-05-01T00:00:00Z",
    )

    determination = X.open_determination(client, depositor["id"])
    prepared = X.prepare(client, determination["id"])
    assert_determination_amounts(prepared, 5000000, 0, 5000000)
    assert_category_breakdown(prepared, "SINGLE", 5000000, C.SMDIA_CENTS, 5000000, 0)

    assert_account_dimensions(
        X.get_account(client, late_account["id"]),
        "PENDING",
        "NONE",
        "PENDING",
        held_amount_cents=0,
        attributed_amount_cents=0,
    )
    assert_account_dimensions(
        X.get_account(client, frozen_account["id"]),
        "FROZEN_FOR_DETERMINATION",
        "NONE",
        "PENDING",
        held_amount_cents=0,
        attributed_amount_cents=5000000,
    )

    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        total_deposit_balance_cents=8000000,
        attributed_total_cents=5000000,
        unattributed_balance_cents=3000000,
    )
    assert_conservation_identities_hold(summary)


# ---------------------------------------------------------------------------
# The uninsured hold allocation: truncate, then distribute the remainder
# ---------------------------------------------------------------------------
def test_hold_allocation_two_cent_remainder_follows_account_number_tiebreak(client):
    """Three equal accounts sharing an uninsured remainder each take a truncated share,
    and the leftover cents go one at a time in account-number order.

    PRD: "Truncating every share leaves a remainder — the uninsured amount minus the sum of the truncated holds, which is always at least zero and always smaller than the number of eligible accounts — and that remainder is distributed one cent at a time to the eligible accounts in the same `created_at` ascending, `account_number` ascending order until it is exhausted."

    Design: Corner/calculations/hold_allocation_two_cent_remainder_follows_account_number_tiebreak
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61032",
        legal_name="Remainder Bank",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    depositor = X.new_depositor(
        client, institution["id"], tin_hash="TIN-HR-1", legal_name="Basil Nwosu"
    )
    accounts = [
        X.new_account(
            client,
            institution["id"],
            depositor["id"],
            account_number=number,
            ownership_category="SINGLE",
            balance_cents=10000000,
            accrued_interest_cents=0,
        )
        for number in ("HA-0001", "HA-0002", "HA-0003")
    ]
    X.make_resolution_ready(client, institution["id"], 30000000)
    X.close_charter(client, institution["id"])

    determination = X.open_determination(client, depositor["id"])
    X.prepare(client, determination["id"])
    X.submit_review(client, determination["id"])
    certified = X.certify(client, determination["id"])

    # 30000000 pooled against one standard maximum leaves 5000000 uninsured.
    assert_determination_amounts(certified, C.SMDIA_CENTS, 5000000, 30000000)

    # 5000000 * 10000000 / 30000000 truncates to 1666666 three times, leaving 2 cents.
    held = [X.get_account(client, account["id"])["held_amount_cents"] for account in accounts]
    assert held == [1666667, 1666667, 1666666], held
    for account in accounts:
        row = X.get_account(client, account["id"])
        assert_account_dimensions(row, "DETERMINED", "HELD", "PENDING")
        assert_cents(row["held_amount_cents"])
    assert sum(held) == certified["uninsured_amount_cents"]

    certificates = X.certificates_of(client, institution["id"])
    assert len(certificates) == 1, certificates
    assert_certificate(certificates[0], "ISSUED", 5000000, cumulative_dividends_cents=0)

    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        held_amount_total_cents=5000000,
        aggregate_certificate_face_cents=5000000,
        uninsured_claim_count=1,
    )
    assert_conservation_identities_hold(summary)


# ---------------------------------------------------------------------------
# The least-cost test: the liquidation baseline and the nine priced bid steps
# ---------------------------------------------------------------------------
def test_liquidation_baseline_floors_insured_share_then_rounds_subrogation(client):
    """The baseline truncates the insured share to whole basis points first and only then
    rounds the subrogated recovery half up, and counts every depositor's admin cost.

    PRD: "The baseline is then `aggregate_insured_cents`, plus an administrative cost of 150000 cents — 1500 dollars — for each depositor counted in `depositor_record_count`, minus that subrogated recovery."

    Design: Corner/calculations/liquidation_baseline_floors_insured_share_then_rounds_subrogation
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61033",
        legal_name="Baseline Precision Bank",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=4005000,
    )
    cleo = X.new_depositor(
        client, institution["id"], tin_hash="TIN-BL-1", legal_name="Cleo Marchetti"
    )
    dario = X.new_depositor(
        client, institution["id"], tin_hash="TIN-BL-2", legal_name="Dario Ferreira"
    )
    X.new_account(
        client,
        institution["id"],
        cleo["id"],
        account_number="BL-0001",
        ownership_category="SINGLE",
        balance_cents=7000000,
        accrued_interest_cents=0,
    )
    X.new_account(
        client,
        institution["id"],
        dario["id"],
        account_number="BL-0002",
        ownership_category="SINGLE",
        balance_cents=2000000,
        accrued_interest_cents=0,
    )
    X.make_resolution_ready(client, institution["id"], 9000000)
    X.close_charter(client, institution["id"])

    # Only Cleo's position is certified, so only her 7000000 is insured coverage.
    X.certified_determination(client, cleo["id"])
    X.open_marketing(client, institution["id"], bid_deadline_at="2026-08-10T00:00:00Z")

    evaluated = X.evaluate_least_cost(client, institution["id"], "EXPECTED_LOSS_SHARE")

    # insured share floor(7000000 * 10000 / 9000000) = 7777 basis points;
    # subrogated recovery round_half_up(4005000 * 7777 / 10000) = 3114689;
    # baseline 7000000 + 150000 * 2 - 3114689 = 4185311.
    expected_baseline = (
        7000000 + C.ADMIN_COST_PER_DEPOSITOR_CENTS * 2 - 3114689
    )
    assert expected_baseline == 4185311
    assert_fields_equal(evaluated, {"liquidation_baseline_cents": expected_baseline})
    assert_cents(evaluated["liquidation_baseline_cents"])
    assert_institution_aggregates(
        evaluated,
        aggregate_insured_cents=7000000,
        total_deposit_balance_cents=9000000,
        depositor_record_count=2,
    )
    assert_fields_equal(
        evaluated,
        {
            "least_cost_status": "EVALUATED",
            "least_cost_test_variant": "EXPECTED_LOSS_SHARE",
            "conforming_bid_count": 0,
        },
    )


def test_bid_cost_base_switch_and_fee_gates_across_three_structures(client):
    """One evaluation prices three structures on identical terms: the insured-only bid
    swaps its deposit base, and only the loss-share bid books a fee and a reimbursement.

    PRD: "The **assumed deposit base** is the institution's `aggregate_insured_cents` when the bid's `structure` is `INSURED_DEPOSITS_ONLY_PA`, and the institution's `total_deposit_balance_cents` for every other structure."

    Design: Corner/calculations/bid_cost_base_switch_and_fee_gates_across_three_structures
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61034",
        legal_name="Structure Gate Bank",
        book_asset_value_cents=12000000,
        estimated_liquidation_recovery_cents=6000000,
    )
    elin = X.new_depositor(
        client, institution["id"], tin_hash="TIN-SG-1", legal_name="Elin Vasquez"
    )
    farid = X.new_depositor(
        client, institution["id"], tin_hash="TIN-SG-2", legal_name="Farid Yusuf"
    )
    X.new_account(
        client,
        institution["id"],
        elin["id"],
        account_number="SG-0001",
        ownership_category="SINGLE",
        balance_cents=15000000,
        accrued_interest_cents=0,
    )
    X.new_account(
        client,
        institution["id"],
        farid["id"],
        account_number="SG-0002",
        ownership_category="SINGLE",
        balance_cents=5000000,
        accrued_interest_cents=0,
    )
    X.make_resolution_ready(client, institution["id"], 20000000)
    X.close_charter(client, institution["id"])
    X.certified_determination(client, elin["id"])
    X.open_marketing(client, institution["id"], bid_deadline_at="2026-08-10T00:00:00Z")

    whole_bank = X.new_qualified_bidder(
        client,
        legal_name="Whole Bank Acquirer",
        cert_number="61035",
        tier1_capital_ratio_bps=1400,
        camels_composite=2,
    )
    insured_only = X.new_qualified_bidder(
        client,
        legal_name="Insured Only Acquirer Two",
        cert_number="61036",
        tier1_capital_ratio_bps=1450,
        camels_composite=1,
    )
    loss_share = X.new_qualified_bidder(
        client,
        legal_name="Loss Share Acquirer",
        cert_number="61037",
        tier1_capital_ratio_bps=1500,
        camels_composite=2,
    )

    # Identical terms on all three bids; only `structure` differs.
    whole_bank_bid = X.new_bid(
        client,
        institution["id"],
        whole_bank["id"],
        structure="WHOLE_BANK_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        loss_share_pct_bps=4000,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T09:00:00Z",
        data_room_window_end="2026-08-04T10:00:00Z",
    )
    insured_only_bid = X.new_bid(
        client,
        institution["id"],
        insured_only["id"],
        structure="INSURED_DEPOSITS_ONLY_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        loss_share_pct_bps=0,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T12:00:00Z",
        data_room_window_end="2026-08-04T13:00:00Z",
    )
    loss_share_bid = X.new_bid(
        client,
        institution["id"],
        loss_share["id"],
        structure="LOSS_SHARE_PA",
        deposit_premium_bps=200,
        asset_discount_bps=1500,
        loss_share_pct_bps=4000,
        asset_retention_pool_cents=0,
        data_room_window_start="2026-08-04T15:00:00Z",
        data_room_window_end="2026-08-04T16:00:00Z",
    )

    evaluated = X.evaluate_least_cost(client, institution["id"], "EXPECTED_LOSS_SHARE")
    # insured share floor(15000000 * 10000 / 20000000) = 7500;
    # subrogated round_half_up(6000000 * 7500 / 10000) = 4500000;
    # baseline 15000000 + 150000 * 2 - 4500000 = 10800000.
    assert_fields_equal(
        evaluated,
        {"liquidation_baseline_cents": 10800000, "conforming_bid_count": 3},
    )

    # Transferred asset value 12000000 and asset bid value 10200000 are shared.
    whole_bank_row = X.get_bid(client, whole_bank_bid["id"])
    assert_fields_equal(whole_bank_row, {"status": "CONFORMING"})
    assert_bid_costs(whole_bank_row, 20000000, 9400000, 0, 0, 9400000)

    insured_only_row = X.get_bid(client, insured_only_bid["id"])
    assert_fields_equal(insured_only_row, {"status": "CONFORMING"})
    assert_bid_costs(insured_only_row, 15000000, 4500000, 0, 0, 4500000)

    loss_share_row = X.get_bid(client, loss_share_bid["id"])
    assert_fields_equal(loss_share_row, {"status": "CONFORMING"})
    # Tier B keyed on the pre-fee cost gives 40 basis points of 9400000 = 37600,
    # and 12000000 * 1800 * 4000 / 100000000 = 864000.
    assert_bid_costs(loss_share_row, 20000000, 9400000, 37600, 864000, 10301600)


# ---------------------------------------------------------------------------
# The dividend waterfall and the receivership cash identity
# ---------------------------------------------------------------------------
def test_dividend_insured_subrogation_round_touches_no_certificate(client):
    """A subrogation round pays the insurance fund a rate on the institution's certified
    insured coverage and leaves every depositor certificate untouched.

    PRD: "For an `INSURED_SUBROGATION` round, the payout total is the institution's `aggregate_insured_cents` multiplied by the round's `declared_rate_bps`, divided by 10000, rounded half up. No receivership certificate is touched at all and the round's `certificate_count` is 0"

    Design: Corner/calculations/dividend_insured_subrogation_round_touches_no_certificate
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61038",
        legal_name="Subrogation Round Bank",
        charter_state="MN",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    gita = X.new_depositor(
        client, institution["id"], tin_hash="TIN-SUB-1", legal_name="Gita Raman"
    )
    X.new_account(
        client,
        institution["id"],
        gita["id"],
        account_number="SUB-0001",
        ownership_category="SINGLE",
        balance_cents=30000000,
        accrued_interest_cents=0,
        opened_at="2023-11-01T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], 30000000)
    X.close_charter(client, institution["id"])

    determination = X.certified_determination(client, gita["id"])
    certificate = X.certificate_for(client, determination["id"])
    assert_certificate(certificate, "ISSUED", 5000000, cumulative_dividends_cents=0)

    X.post_proceeds(
        client,
        institution["id"],
        asset_pool_code="POOL-SUB-A",
        gross_proceeds_cents=10000000,
        disposition_expense_cents=0,
    )

    declared = X.declare_dividend(client, institution["id"], "INSURED_SUBROGATION", 1000)
    settled = X.settle_dividend(client, declared["id"])

    # 25000000 of certified coverage at 1000 basis points is 2500000 cents.
    assert_fields_equal(
        settled,
        {
            "status": "SETTLED",
            "total_distributed_cents": 2500000,
            "certificate_count": 0,
        },
    )
    assert_cents(settled["total_distributed_cents"])

    assert_certificate(
        X.get_certificate(client, certificate["id"]),
        "ISSUED",
        5000000,
        cumulative_dividends_cents=0,
        last_dividend_amount_cents=0,
        last_dividend_round=0,
    )

    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary, receivership_cash_cents=7500000, dividends_paid_cents=2500000
    )
    assert_conservation_identities_hold(summary)


def test_dividend_payable_capped_at_remaining_face_then_paid_certificate_excluded(client):
    """Successive general-unsecured rounds pay a certificate down, cap the second payment
    at the unpaid face, and then find an empty claim set once the certificate is paid.

    PRD: "the payable amount is the smaller of that gross entitlement and the certificate's remaining face, which is `face_amount_cents` minus `cumulative_dividends_cents`."

    Design: Corner/calculations/dividend_payable_capped_at_remaining_face_then_paid_certificate_excluded
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61039",
        legal_name="Waterfall Cap Bank",
        charter_state="IA",
        book_asset_value_cents=40000000,
        estimated_liquidation_recovery_cents=15000000,
    )
    hosea = X.new_depositor(
        client, institution["id"], tin_hash="TIN-WF-1", legal_name="Hosea Bright"
    )
    X.new_account(
        client,
        institution["id"],
        hosea["id"],
        account_number="WF-0001",
        ownership_category="SINGLE",
        balance_cents=30000000,
        accrued_interest_cents=0,
        opened_at="2023-09-01T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], 30000000)
    X.close_charter(client, institution["id"])

    determination = X.certified_determination(client, hosea["id"])
    certificate = X.certificate_for(client, determination["id"])
    X.post_proceeds(
        client,
        institution["id"],
        asset_pool_code="POOL-WF-A",
        gross_proceeds_cents=10000000,
        disposition_expense_cents=0,
    )

    # Round one at 6000 basis points pays 3000000 of the 5000000 face.
    round_one = X.declare_dividend(client, institution["id"], "GENERAL_UNSECURED", 6000)
    assert_fields_equal(
        round_one, {"status": "DECLARED", "distribution_round": 1, "declared_rate_bps": 6000}
    )
    settled_one = X.settle_dividend(client, round_one["id"])
    assert_fields_equal(
        settled_one,
        {"status": "SETTLED", "total_distributed_cents": 3000000, "certificate_count": 1},
    )
    assert_certificate(
        X.get_certificate(client, certificate["id"]),
        "PARTIALLY_PAID",
        5000000,
        cumulative_dividends_cents=3000000,
        last_dividend_amount_cents=3000000,
        last_dividend_round=1,
    )

    # Round two computes 4000000 but only 2000000 of face remains unpaid.
    round_two = X.declare_dividend(client, institution["id"], "GENERAL_UNSECURED", 8000)
    assert_fields_equal(round_two, {"distribution_round": 2})
    settled_two = X.settle_dividend(client, round_two["id"])
    assert_fields_equal(
        settled_two,
        {"status": "SETTLED", "total_distributed_cents": 2000000, "certificate_count": 1},
    )
    assert_certificate(
        X.get_certificate(client, certificate["id"]),
        "PAID",
        5000000,
        cumulative_dividends_cents=5000000,
        last_dividend_amount_cents=2000000,
        last_dividend_round=2,
    )

    # Round three finds no eligible claim, since a paid certificate leaves the claim set.
    round_three = X.declare_dividend(client, institution["id"], "GENERAL_UNSECURED", 1000)
    assert_fields_equal(round_three, {"distribution_round": 3})
    settled_three = X.settle_dividend(client, round_three["id"])
    assert_fields_equal(
        settled_three,
        {"status": "SETTLED", "total_distributed_cents": 0, "certificate_count": 0},
    )
    assert_certificate(
        X.get_certificate(client, certificate["id"]),
        "PAID",
        5000000,
        cumulative_dividends_cents=5000000,
        last_dividend_amount_cents=2000000,
        last_dividend_round=2,
    )

    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary, receivership_cash_cents=5000000, dividends_paid_cents=5000000
    )
    assert_conservation_identities_hold(summary)


def test_receivership_proceeds_accumulate_into_cash_conservation(client):
    """Two dispositions from different asset pools accumulate into the estate's running
    gross, expense and cash totals rather than overwriting them.

    PRD: "A successful posting adds the gross figure to the institution's `gross_disposition_proceeds_cents`, adds the expense figure to `disposition_expense_total_cents`, increases `receivership_cash_cents` by the difference between them, and bumps the institution's `version`."

    Design: Corner/calculations/receivership_proceeds_accumulate_into_cash_conservation
    """
    X.open_at_setup_clock(client)
    institution = X.new_institution(
        client,
        cert_number="61040",
        legal_name="Proceeds Accumulation Bank",
        charter_state="NE",
        book_asset_value_cents=20000000,
        estimated_liquidation_recovery_cents=8000000,
    )
    ines = X.new_depositor(
        client, institution["id"], tin_hash="TIN-PA-1", legal_name="Ines Correa"
    )
    X.new_account(
        client,
        institution["id"],
        ines["id"],
        account_number="PA-0001",
        ownership_category="SINGLE",
        balance_cents=6000000,
        accrued_interest_cents=0,
        opened_at="2024-01-15T00:00:00Z",
    )
    X.make_resolution_ready(client, institution["id"], 6000000)
    X.close_charter(client, institution["id"])

    first = X.post_proceeds(
        client,
        institution["id"],
        asset_pool_code="POOL-A",
        gross_proceeds_cents=10000000,
        disposition_expense_cents=1200000,
    )
    assert_institution_aggregates(
        first,
        gross_disposition_proceeds_cents=10000000,
        disposition_expense_total_cents=1200000,
        receivership_cash_cents=8800000,
    )
    assert_institution_aggregates(
        X.get_institution(client, institution["id"]), receivership_cash_cents=8800000
    )

    second = X.post_proceeds(
        client,
        institution["id"],
        asset_pool_code="POOL-B",
        gross_proceeds_cents=4000000,
        disposition_expense_cents=0,
    )
    assert_institution_aggregates(
        second,
        gross_disposition_proceeds_cents=14000000,
        disposition_expense_total_cents=1200000,
        receivership_cash_cents=12800000,
    )

    summary = X.insurance_summary(client, institution["id"])
    assert_summary(
        summary,
        gross_disposition_proceeds_cents=14000000,
        disposition_expense_total_cents=1200000,
        dividends_paid_cents=0,
        receivership_cash_cents=12800000,
    )
    assert_conservation_identities_hold(summary)
