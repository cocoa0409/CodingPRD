"""Judicial package preparation, sealing, and delivery.

PRD §3.7, §2.10 priorities 7/14/15/19.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    assert_judicial_package,
    bring_evidence_to_confirmed,
    create_certificate,
    create_customer_with_balance,
    create_evidence,
    create_judicial_package,
    create_judicial_package_payload,
    create_notarization,
    deliver_judicial_package,
    get_customer,
    judicial_ack_payload,
    judicial_surcharge_cents,
    list_audit_logs,
    make_customer_headers,
    seal_judicial_package,
    setup_sealed_judicial_package,
    submit_evidence,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import JUDICIAL


# ===========================================================================
# Preparation (PRD §3.7)
# ===========================================================================
class TestJudicialPackagePrepare:
    """PRD §3.7: 'A JudicialOfficer prepares evidence for delivery to
    a court, procuratorate, or arbitration tribunal by opening a
    JudicialPackage in DRAFT. The preparation payload carries the
    evidence_id, a court-assigned case_number (non-empty, at most 64
    characters), a structured party_info JSON object with plaintiff and
    defendant records, an authority_code ... and a boolean
    include_original_data (default false)'."""

    def test_create_draft_package(self, api):
        customer, ev = bring_evidence_to_confirmed()
        res = api.create_judicial_package(
            create_judicial_package_payload(
                evidence_id=ev["id"],
                authority_code="COURT_BJ",
            ),
            JUDICIAL,
        )
        pkg = validate_success(res, 201)
        assert_judicial_package(pkg)
        assert pkg["status"] == "DRAFT"
        assert pkg["evidence_id"] == ev["id"]
        assert pkg["authority_code"] == "COURT_BJ"
        assert pkg["surcharge_cents"] is None
        assert pkg["official_seal_id"] is None
        assert pkg["delivered_at"] is None


# ===========================================================================
# Sealing preconditions (priority 7, 14, 19)
# ===========================================================================
class TestSealPreconditions:
    """PRD §3.7: 'The transition's preconditions are that the linked
    Evidence.status is CONFIRMED, the linked Certificate.status is
    ISSUED (a missing or REVOKED certificate rejects the seal with
    ERR_CERTIFICATE_REQUIRED), the linked TimestampNotarization exists,
    and Customer.wallet_balance_cents is at least the forward-looking
    judicial surcharge quote.'"""

    def test_seal_without_certificate_rejected(self, api):
        """PRD §2.10 priority 14: 'JudicialPackage.case_number is
        non-empty and the linked Certificate exists with status equal
        to ISSUED at seal time (ERR_CERTIFICATE_REQUIRED).'"""
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        pkg = create_judicial_package(ev)
        # No Certificate issued.
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)

    def test_seal_with_revoked_certificate_rejected(self, api,
                                                    admin_headers):
        """PRD §3.7: 'a missing or REVOKED certificate rejects the seal
        with ERR_CERTIFICATE_REQUIRED'."""
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        cert = create_certificate(ev)
        # Admin revokes the cert.
        validate_success(
            api.revoke_certificate(cert["id"], admin_headers), 200,
        )
        pkg = create_judicial_package(ev)
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_CERTIFICATE_REQUIRED.value)

    def test_seal_with_insufficient_balance_rejected(self, api):
        """PRD §2.10 priority 19: 'Customer.wallet_balance_cents is at
        least the forward-looking judicial surcharge quote on judicial
        seal (ERR_INSUFFICIENT_BALANCE).'

        ARBITRATION authority: (5000 + 0) * 0.90 = 4500.
        """
        customer, ev = bring_evidence_to_confirmed(balance_cents=1_000)
        # balance_cents 1000 spent — debit 200 (DOCUMENT/30/no original)
        # so balance is 800; need 4500 for ARBITRATION seal.
        create_certificate(ev)
        pkg = create_judicial_package(
            ev, authority_code="ARBITRATION",
        )
        res = api.seal_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_BALANCE.value)


# ===========================================================================
# Sealing side effects (PRD §3.7)
# ===========================================================================
class TestSealSideEffects:
    """PRD §3.7: 'A successful seal mints a fresh official_seal_id,
    assigns the surcharge to JudicialPackage.surcharge_cents, debits
    the customer's wallet_balance_cents by that amount, increments
    FeeAccount.lifetime_deduction_cents by the same amount, and appends
    audit rows of event_type JUDICIAL_SEALED and FEE_DEBITED.'

    Surcharge formula (PRD §3.7): start with 5000, add 1500 if
    include_original_data else 0, multiply by authority multiplier,
    round half-up."""

    def test_seal_court_bj_no_original_data_surcharge(self, api):
        """PRD §3.7: 'COURT_BJ ... is 1.20'.
        Surcharge = round((5000 + 0) * 1.20) = 6000.
        Difficulty design
        'judicial_surcharge_quote_vs_final_on_judicial_package_entity'.
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="COURT_BJ",
            include_original_data=False,
            balance_cents=100_000,
        )
        assert sealed["status"] == "SEALED"
        assert sealed["surcharge_cents"] == 6000
        assert sealed["official_seal_id"] is not None

    def test_seal_with_original_data_uplift_and_court_bj(self, api):
        """PRD §3.7: 'add 1500 cents when include_original_data is true
        and zero when it is false, then multiply ... COURT_BJ ... 1.20'.
        Surcharge = round((5000 + 1500) * 1.20) = 7800.
        Difficulty design 'judicial_surcharge_mode_a_nonlinear_three_inputs'.
        """
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="COURT_BJ",
            include_original_data=True,
            balance_cents=100_000,
        )
        assert sealed["surcharge_cents"] == 7800

    @pytest.mark.parametrize("authority,expected", [
        ("COURT_BJ", 6000),       # (5000 + 0) * 1.20
        ("COURT_SH", 6000),       # (5000 + 0) * 1.20
        ("COURT_GZ", 5500),       # (5000 + 0) * 1.10
        ("COURT_SZ", 5500),       # (5000 + 0) * 1.10
        ("PROCURATORATE", 5000),  # (5000 + 0) * 1.00
        ("ARBITRATION", 4500),    # (5000 + 0) * 0.90
    ])
    def test_authority_multipliers(self, api, authority, expected):
        """PRD §3.7: 'COURT_BJ and COURT_SH are 1.20, COURT_GZ and
        COURT_SZ are 1.10, PROCURATORATE is 1.00, and ARBITRATION is
        0.90'."""
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code=authority,
            include_original_data=False,
            balance_cents=100_000,
        )
        assert sealed["surcharge_cents"] == expected

    def test_seal_debits_wallet_and_increments_ledger(self, api):
        """PRD §3.7: 'debits the customer's wallet_balance_cents by that
        amount, increments FeeAccount.lifetime_deduction_cents by the
        same amount'."""
        # confirmed evidence debits 200 (DOCUMENT/30 default).
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            authority_code="COURT_BJ", balance_cents=100_000,
        )
        cust_after = get_customer(customer["id"])
        # 100_000 - 200 (preservation) - 6000 (seal) = 93_800
        assert cust_after["wallet_balance_cents"] == 93_800

    def test_seal_appends_audit_events(self, api):
        """PRD §3.7: 'appends audit rows of event_type JUDICIAL_SEALED
        and FEE_DEBITED.'"""
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
        )
        seal_rows = list_audit_logs(
            event_type="JUDICIAL_SEALED",
            target_entity="JudicialPackage",
            target_id=sealed["id"],
        )
        assert len(seal_rows) >= 1
        fee_rows = list_audit_logs(
            event_type="FEE_DEBITED",
            target_entity="JudicialPackage",
            target_id=sealed["id"],
        )
        assert len(fee_rows) >= 1


# ===========================================================================
# Delivery (PRD §3.7)
# ===========================================================================
class TestJudicialDelivery:
    """PRD §3.7: 'A JudicialOfficer records the delivery directly, or
    the platform delivers the same transition via the judicial
    acknowledgement event that names the affected judicial_package_id.
    The transition sets JudicialPackage.delivered_at to the server's
    current time and appends an audit row of type JUDICIAL_DELIVERED.'"""

    def test_deliver_from_sealed_succeeds(self, api):
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
        )
        res = api.deliver_judicial_package(sealed["id"], JUDICIAL)
        delivered = validate_success(res, 200)
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_at"] is not None

    def test_deliver_from_draft_rejected(self, api):
        """PRD §2.10 priority 6: a DRAFT package cannot be DELIVERED."""
        customer, ev = bring_evidence_to_confirmed(balance_cents=100_000)
        create_certificate(ev)
        pkg = create_judicial_package(ev)
        res = api.deliver_judicial_package(pkg["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_judicial_ack_event_drives_delivery(self, api,
                                                 admin_headers):
        """PRD §3.10: 'judicial acknowledgement capability drives a
        named JudicialPackage from SEALED to DELIVERED.'"""
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
        )
        res = api.deliver_judicial_ack(
            judicial_ack_payload(judicial_package_id=sealed["id"]),
            admin_headers,
        )
        validate_success(res, 200)
        from test_helpers import api_client
        got = validate_success(api_client.get_judicial_package(
            sealed["id"], JUDICIAL,
        ), 200)
        assert got["status"] == "DELIVERED"


# ===========================================================================
# Concurrent seal serialization (PRD §2.11)
# ===========================================================================
class TestSealStateGuard:
    """PRD §2.11: 'Two simultaneous seals of the same DRAFT
    JudicialPackage likewise serialise on JudicialPackage.status; the
    loser receives ERR_INVALID_STATE.'"""

    def test_double_seal_rejected(self, api):
        """PRD §2.11: 'the loser receives ERR_INVALID_STATE.'
        Sequentially, the second seal on the same already-SEALED package
        must reject with ERR_INVALID_STATE."""
        customer, ev, cert, sealed = setup_sealed_judicial_package(
            balance_cents=100_000,
        )
        # Sealed once. A second seal must fail with INVALID_STATE.
        res = api.seal_judicial_package(sealed["id"], JUDICIAL)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
