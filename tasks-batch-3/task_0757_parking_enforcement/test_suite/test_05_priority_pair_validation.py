"""Difficulty rule: priority_pair_validation_conflict.

When two checks could both reject a request, the fixed precedence of §2.10
determines which error is returned:
  (A) POST /payments on a VOID citation with an over-limit amount: State (6)
      beats Fiscal bounds (9) -> ERR_CITATION_NOT_PAYABLE;
  (B) POST /citations with a non-existent vehicle and a RETIRED code:
      Existence (3) beats Eligibility (8) -> ERR_VEHICLE_NOT_FOUND.
"""
from test_helpers import (
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    make_enforcement_officer_headers,
    setup_issuing_context,
    issue_in_context,
    void_citation,
    create_officer,
    create_beat,
    create_violation_code,
    retire_violation_code,
    create_vehicle,
    open_shift,
)

MOTORIST = TEST_USERS["motorist_headers"]


class TestPaymentStateBeatsFiscal:
    def _void_citation_ctx(self):
        ctx = setup_issuing_context(base_fine_cents=15000, code="HYDRANT")
        cit = issue_in_context(ctx)
        void_citation(cit["id"])
        return cit

    def test_overlimit_payment_on_void_citation_returns_not_payable(self, api):
        """PRD §2.10: "6. **State** — the target resource is in a state that permits
        the requested transition, else the applicable conflict error (409), such as
        `ERR_INVALID_STATE`, `ERR_SHIFT_NOT_OPEN`, `ERR_CITATION_NOT_PAYABLE`,
        `ERR_CITATION_NOT_CONTESTABLE`, `ERR_PAYMENT_NOT_REFUNDABLE`,
        `ERR_CONTEST_ALREADY_EXISTS`, or `ERR_BOOT_ALREADY_ACTIVE`."
        PRD §3.5: "The target citation must be payable — that is, in `status` `ISSUED`
        or `UPHELD` — or the payment is rejected with `ERR_CITATION_NOT_PAYABLE`."

        Design: Difficulty/priority_pair_validation_conflict/payment_void_state_beats_amount_fiscal
        """
        cit = self._void_citation_ctx()
        validate_error(
            api.create_payment(
                {"citation_id": cit["id"], "amount_cents": 999999, "method": "CARD"},
                MOTORIST),
            ApiErrorId.ERR_CITATION_NOT_PAYABLE.value)

    def test_state_error_precedes_fiscal_regardless_of_amount(self, api):
        """PRD §2.10: "9. **Fiscal bounds** — for recording a payment, applying a
        waiver, and reassessing a fine, the monetary amounts are within their
        permitted ranges, else `ERR_PAYMENT_AMOUNT_MISMATCH`,
        `ERR_ADJUSTMENT_EXCEEDS_BALANCE`, or `ERR_VALIDATION` (422)."
        PRD §3.5: "The target citation must be payable — that is, in `status` `ISSUED`
        or `UPHELD` — or the payment is rejected with `ERR_CITATION_NOT_PAYABLE`."

        Design: Difficulty/priority_pair_validation_conflict/payment_void_state_beats_amount_fiscal
        """
        # A minimal amount would also breach the fiscal bound (amount_due is 0 on a
        # VOID citation), yet the earlier State check still wins.
        cit = self._void_citation_ctx()
        validate_error(
            api.create_payment(
                {"citation_id": cit["id"], "amount_cents": 1, "method": "CARD"},
                MOTORIST),
            ApiErrorId.ERR_CITATION_NOT_PAYABLE.value)


class TestCitationExistenceBeatsRetired:
    def _officer_shift_and_retired_code(self):
        officer = create_officer(badge_number="B-PP2")
        beat = create_beat(patrol_zone="RESIDENTIAL", beat_code="RES9")
        vc = create_violation_code(code="OLD_CODE", description="Deprecated code",
                                   base_fine_cents=5000, is_booting_eligible=False)
        retire_violation_code(vc["id"])
        shift = open_shift(officer["id"], beat["id"])
        return officer, vc, shift

    def test_nonexistent_vehicle_beats_retired_code(self, api):
        """PRD §2.10: "3. **Existence** — all referenced resources resolve left to
        right (§2.9), else the entity's not-found error (404). Applies to every
        endpoint that references a resource id."
        PRD §2.9: "References are validated left to right: path identifiers first,
        then body foreign keys in the order they are declared for that operation."

        Design: Difficulty/priority_pair_validation_conflict/citation_issue_existence_beats_retired_constraint
        """
        officer, vc, shift = self._officer_shift_and_retired_code()
        validate_error(
            api.create_citation(
                {"vehicle_id": NON_EXISTENT_UUID, "shift_id": shift["id"],
                 "violation_code_id": vc["id"], "issued_via": "HANDHELD",
                 "evidence_photo_url": "https://ev/x.jpg"},
                make_enforcement_officer_headers(officer["id"])),
            ApiErrorId.ERR_VEHICLE_NOT_FOUND.value)

    def test_retired_code_fires_once_existence_passes(self, api):
        """PRD §3.3: "the shift must be `OPEN` (else `ERR_SHIFT_NOT_OPEN`) and the
        violation code must be `ACTIVE` (else `ERR_VIOLATION_CODE_RETIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/citation_issue_existence_beats_retired_constraint
        """
        officer, vc, shift = self._officer_shift_and_retired_code()
        vehicle = create_vehicle(plate="PP2PLT")
        validate_error(
            api.create_citation(
                {"vehicle_id": vehicle["id"], "shift_id": shift["id"],
                 "violation_code_id": vc["id"], "issued_via": "HANDHELD",
                 "evidence_photo_url": "https://ev/x.jpg"},
                make_enforcement_officer_headers(officer["id"])),
            ApiErrorId.ERR_VIOLATION_CODE_RETIRED.value)
