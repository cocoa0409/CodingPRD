"""Optimistic concurrency control and version increments."""
from test_helpers import (
    ApiErrorId,
    approve_dmr,
    create_agreement,
    create_agreement_payload,
    create_approved_dmr,
    create_dmr_draft,
    create_revision_payload,
    create_supplier,
    qe,
    qm,
    sqe,
    validate_error,
    validate_success,
    api_client,
)


class TestOccAgreementCreate:
    def test_stale_supplier_version_rejected_and_fresh_retry_supersedes(self, api):
        """PRD section 2.7: "**Quality-agreement creation** against a supplier
        requires the request to carry `expected_supplier_version` equal to that
        supplier's current `version`. If another writer has advanced the
        supplier's version since the client last read it, the create is rejected
        with `ERR_STALE_VERSION` (HTTP 412)" and PRD section 3.4: "its creation
        supersedes every existing `DRAFT` agreement of the same supplier".

        Design: Corner/cross_cutting_layers/occ_agreement_create_stale_supplier_version
        """
        supplier = create_supplier("SUP-OCC1", "OCC One")
        observed_version = supplier["version"]

        first = create_agreement(supplier, agreement_code="QA-OCC1-A")
        assert first["status"] == "DRAFT"

        resp = api.create_agreement(
            supplier["id"],
            create_agreement_payload(observed_version, agreement_code="QA-OCC1-B"),
            sqe(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_supplier(supplier["id"], sqe()))
        retry = validate_success(
            api.create_agreement(
                supplier["id"],
                create_agreement_payload(fresh["version"], agreement_code="QA-OCC1-C"),
                sqe(),
            ),
            expected_status=201,
        )
        assert retry["status"] == "DRAFT"

        superseded = validate_success(api.get_agreement(first["id"], sqe()))
        assert superseded["status"] == "SUPERSEDED"


class TestOccRevisionCreate:
    def test_stale_dmr_version_rejected_and_fresh_retry_succeeds(self, api):
        """PRD section 2.7: "**Successor-revision creation** against a Device
        Master Record requires `expected_dmr_version` equal to the parent
        revision's current `version`, with a mismatch rejected as
        `ERR_STALE_VERSION` (HTTP 412)." and PRD section 3.1: "receives
        `revision_seq` one greater than its parent's, records the parent revision
        in `parent_dmr_id`, and starts in `DRAFT`."

        Design: Corner/cross_cutting_layers/occ_revision_create_stale_dmr_version
        """
        dmr_a = create_approved_dmr(device_code="DEV-OCC2")
        observed_version = dmr_a["version"]

        rev_b = validate_success(
            api.create_dmr_revision(
                dmr_a["id"],
                create_revision_payload(observed_version, revision_code="B",
                                        shelf_life_claim_months=24, sterile=True),
                qe(),
            ),
            expected_status=201,
        )
        assert rev_b["status"] == "DRAFT"

        resp = api.create_dmr_revision(
            dmr_a["id"],
            create_revision_payload(observed_version, revision_code="C",
                                    shelf_life_claim_months=30, sterile=True),
            qe(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_a = validate_success(api.get_dmr(dmr_a["id"], qm()))
        rev_c = validate_success(
            api.create_dmr_revision(
                dmr_a["id"],
                create_revision_payload(fresh_a["version"], revision_code="C",
                                        shelf_life_claim_months=30, sterile=True),
                qe(),
            ),
            expected_status=201,
        )
        assert rev_c["revision_seq"] == dmr_a["revision_seq"] + 1
        assert rev_c["parent_dmr_id"] == dmr_a["id"]


class TestVersionIncrements:
    def test_version_increments_only_on_mutations_of_that_resource(self, api):
        """PRD section 2.4: "`version` (integer): a system-managed integer that
        increments by one with every mutation of the resource." and PRD section
        2.7: "Successful creation itself increments the supplier's `version` by
        one as part of its side effects." — activating the agreement mutates the
        agreement, not the supplier.

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        supplier = create_supplier("SUP-VM", "VM Co")
        v_create = supplier["version"]

        agreement = create_agreement(supplier, agreement_code="QA-VM")
        v_after_agreement = validate_success(api.get_supplier(supplier["id"], sqe()))["version"]
        assert v_after_agreement == v_create + 1, (
            "agreement creation increments the parent supplier version by exactly one"
        )

        from test_helpers import activate_agreement

        activate_agreement(agreement["id"])
        v_after_activate = validate_success(api.get_supplier(supplier["id"], sqe()))["version"]
        assert v_after_activate == v_after_agreement, (
            "activating the agreement mutates only the agreement; supplier version unchanged"
        )

        qualified = validate_success(api.qualify_supplier(supplier["id"], sqe()))
        assert qualified["version"] == v_after_agreement + 1, (
            "qualification is a supplier mutation and bumps its version by one"
        )


class TestOccPriority:
    def test_occ_check_precedes_state_check(self, api):
        """PRD section 2.10: "a failure at any step masks all later checks" with
        step "5. **Optimistic concurrency.** On the two version-guarded endpoints
        of §2.7, the expected version matches (`ERR_STALE_VERSION`)" ahead of
        step "7. **State-machine shape.**" — so a stale version against a `DRAFT`
        revision reports the OCC failure, not the state failure.

        Design: Corner/validations/occ_check_precedes_state_check
        """
        dmr = create_dmr_draft(device_code="DEV-OS")
        stale_version = dmr["version"] + 1  # mismatched but well-formed
        resp = api.create_dmr_revision(
            dmr["id"],
            create_revision_payload(stale_version, revision_code="B",
                                    shelf_life_claim_months=30, sterile=True),
            qe(),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
