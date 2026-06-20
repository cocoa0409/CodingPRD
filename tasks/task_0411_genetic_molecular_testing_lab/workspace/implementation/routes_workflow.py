"""Workflow route groups: test orders, requisitions, consents, specimens,
sequencing, variants, reports, billing, sequencers, counselors, referrals.

Registered onto the Flask app by app.py via register(app). All shared helpers
are imported lazily from the app module to avoid circular-import ordering issues.
"""
from flask import request

import serializers as S
from calculations import (
    counselor_slots_conflict,
    patient_responsibility_estimate,
    patient_responsibility_final,
    qns_sufficient,
    sequencer_runs_conflict,
)
from common import (
    ALL_ROLES,
    get_json_body,
    paginate,
    parse_iso,
    require_bool,
    require_enum,
    require_fields,
    require_non_negative_int,
    require_number,
    require_role,
    require_string,
    require_user_context,
)
from db import store
from errors import err
from response import success

ALL = set(ALL_ROLES)


def register(app):
    import app as A  # imported here so app.py has finished defining its helpers
    # ===================================================================
    # TestOrder (PRD 3.2)
    # ===================================================================
    @app.route("/lab/test-orders", methods=["POST"])
    def create_test_order():
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        body = get_json_body()
        require_fields(body, ["patient_mrn", "patient_dob", "panel_id", "ordering_provider_id"])
        patient_mrn = require_string(body, "patient_mrn")
        patient_dob = require_string(body, "patient_dob")
        panel_id = require_string(body, "panel_id")
        provider_id = require_string(body, "ordering_provider_id")
        # Existence checks (panel + provider must exist) before business rule.
        panel = A.get_panel(panel_id)
        A.get_provider(provider_id)
        # Business rule: panel must be PUBLISHED at order time.
        if panel["status"] != "PUBLISHED":
            raise err("ERR_PANEL_NOT_PUBLISHED", "Panel is not in PUBLISHED status.")
        order = {
            "patient_mrn": patient_mrn,
            "patient_dob": patient_dob,
            "panel_id": panel_id,
            "ordering_provider_id": provider_id,
            "pipeline_status": "ORDERED",
            "financial_status": "PENDING",
            "list_price_cents": panel["list_price_cents"],
            "estimated_patient_responsibility_cents": None,
            "final_patient_responsibility_cents": None,
            "report_required_consent": panel["requires_consent"],
            "has_reportable_incidental": False,
            "cancel_reason": None,
        }
        store.stamp_common(order)
        store.test_orders[order["id"]] = order
        # Side effect: create Billing in OPEN status.
        billing = {
            "test_order_id": order["id"],
            "allowed_amount_cents": None,
            "coinsurance_collected_cents": 0,
            "writeoff_cents": 0,
            "status": "OPEN",
        }
        store.stamp_common(billing)
        store.billings[billing["id"]] = billing
        return success(S.test_order(order), 201)

    @app.route("/lab/test-orders", methods=["GET"])
    def list_test_orders():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.test_orders.values())
        for key in ("panel_id", "ordering_provider_id", "pipeline_status", "financial_status"):
            val = request.args.get(key)
            if val is not None:
                items = [o for o in items if o[key] == val]
        page, pag = paginate(items)
        return success([S.test_order(o) for o in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>", methods=["GET"])
    def get_test_order(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.test_order(A.get_order(order_id)), 200)

    @app.route("/lab/test-orders/<order_id>/cancel", methods=["POST"])
    def cancel_order(order_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        order = A.get_order(order_id)
        body = get_json_body()
        cancel_reason = body.get("cancel_reason")
        if cancel_reason is not None and not isinstance(cancel_reason, str):
            raise err("ERR_INVALID_REQUEST", "cancel_reason must be a string.")
        # Cancellable only from non-terminal pipeline states.
        if order["pipeline_status"] not in (
            "ORDERED", "REQUISITIONED", "ACCESSIONED", "SEQUENCING", "CLASSIFIED"
        ):
            raise err("ERR_ORDER_NOT_CANCELLABLE", "Order is already terminal.")
        order["pipeline_status"] = "CANCELLED"
        order["cancel_reason"] = cancel_reason
        store.touch(order)
        # Cascade hop 1: requisition PENDING/SUBMITTED -> VOID.
        req = A.requisition_for_order(order_id)
        if req is not None and req["status"] in ("PENDING", "SUBMITTED"):
            req["status"] = "VOID"
            store.touch(req)
        # Cascade hop 2: billing reversal.
        billing = A.billing_for_order(order_id)
        if billing is not None and billing["status"] in ("AUTH_REQUESTED", "AUTH_APPROVED", "PATIENT_PAY"):
            allowed = billing.get("allowed_amount_cents") or 0
            collected = billing.get("coinsurance_collected_cents") or 0
            diff = allowed - collected
            if diff < 0:
                diff = 0
            billing["writeoff_cents"] = (billing.get("writeoff_cents") or 0) + diff
            billing["coinsurance_collected_cents"] = 0
            billing["status"] = "REVERSED"
            store.touch(billing)
            order["financial_status"] = "SETTLED"
            store.touch(order)
        # Cascade hop 3: referrals REQUESTED/SCHEDULED -> CANCELLED.
        for ref in store.referrals.values():
            if ref["test_order_id"] == order_id and ref["status"] in ("REQUESTED", "SCHEDULED"):
                ref["status"] = "CANCELLED"
                store.touch(ref)
        return success(S.test_order(order), 200)

    # ===================================================================
    # Requisition (PRD 3.2)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/requisition", methods=["POST"])
    def create_requisition(order_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        A.get_order(order_id)
        body = get_json_body()
        require_fields(body, ["clinical_indication", "insurance_payer"])
        indication = require_string(body, "clinical_indication")
        payer = require_enum(body, "insurance_payer", A.INSURANCE_PAYERS)
        req = {
            "test_order_id": order_id,
            "clinical_indication": indication,
            "insurance_payer": payer,
            "status": "PENDING",
        }
        store.stamp_common(req)
        store.requisitions[req["id"]] = req
        return success(S.requisition(req), 201)

    @app.route("/lab/test-orders/<order_id>/requisition", methods=["GET"])
    def list_order_requisition(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [r for r in store.requisitions.values() if r["test_order_id"] == order_id]
        page, pag = paginate(items)
        return success([S.requisition(r) for r in page], 200, pagination=pag)

    @app.route("/lab/requisitions/<requisition_id>", methods=["GET"])
    def get_requisition_route(requisition_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.requisition(A.get_requisition(requisition_id)), 200)

    @app.route("/lab/requisitions", methods=["GET"])
    def list_requisitions():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.requisitions.values())
        for key in ("test_order_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        page, pag = paginate(items)
        return success([S.requisition(r) for r in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/requisition/submit", methods=["POST"])
    def submit_requisition(order_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        order = A.get_order(order_id)
        # State precondition: order must be ORDERED.
        if order["pipeline_status"] != "ORDERED":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in ORDERED status.")
        # A PENDING requisition must exist.
        req = A.requisition_for_order(order_id)
        if req is None or req["status"] != "PENDING":
            raise err("ERR_REQUISITION_NOT_FOUND", "No PENDING requisition for order.")
        # Advance requisition + order.
        req["status"] = "SUBMITTED"
        store.touch(req)
        order["pipeline_status"] = "REQUISITIONED"
        store.touch(order)
        # Fork financial track.
        billing = A.billing_for_order(order_id)
        if req["insurance_payer"] != "SELF_PAY":
            billing["status"] = "AUTH_REQUESTED"
            store.touch(billing)
            order["financial_status"] = "AUTH_REQUESTED"
        else:
            billing["status"] = "PATIENT_PAY"
            billing["allowed_amount_cents"] = order["list_price_cents"]
            store.touch(billing)
            order["financial_status"] = "PATIENT_PAY"
        # Compute the estimate.
        A.recompute_estimate(order, billing)
        store.touch(order)
        return success(S.test_order(order), 200)

    # ===================================================================
    # Consent (PRD 3.3)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/consents", methods=["POST"])
    def create_consent(order_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        A.get_order(order_id)
        body = get_json_body()
        require_fields(body, ["incidental_findings_opt_in", "signed_by_name"])
        opt_in = require_bool(body, "incidental_findings_opt_in")
        signed_by = require_string(body, "signed_by_name")
        c = {
            "test_order_id": order_id,
            "incidental_findings_opt_in": opt_in,
            "signed_by_name": signed_by,
            "status": "DRAFT",
        }
        store.stamp_common(c)
        store.consents[c["id"]] = c
        return success(S.consent(c), 201)

    @app.route("/lab/test-orders/<order_id>/consents", methods=["GET"])
    def list_order_consents(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [c for c in store.consents.values() if c["test_order_id"] == order_id]
        status = request.args.get("status")
        if status is not None:
            items = [c for c in items if c["status"] == status]
        page, pag = paginate(items)
        return success([S.consent(c) for c in page], 200, pagination=pag)

    @app.route("/lab/consents/<consent_id>", methods=["GET"])
    def get_consent_route(consent_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.consent(A.get_consent(consent_id)), 200)

    @app.route("/lab/consents", methods=["GET"])
    def list_consents():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.consents.values())
        for key in ("test_order_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [c for c in items if c[key] == val]
        page, pag = paginate(items)
        return success([S.consent(c) for c in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/consents/<consent_id>/sign", methods=["POST"])
    def sign_consent(order_id, consent_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        A.get_order(order_id)
        c = A.get_consent(consent_id)
        if c["test_order_id"] != order_id:
            raise err("ERR_CONSENT_NOT_FOUND", "Consent does not belong to order.")
        if c["status"] != "DRAFT":
            raise err("ERR_INVALID_REQUEST", "Consent is not in DRAFT status.")
        c["status"] = "SIGNED"
        store.touch(c)
        return success(S.consent(c), 200)

    @app.route("/lab/test-orders/<order_id>/consents/<consent_id>/revoke", methods=["POST"])
    def revoke_consent(order_id, consent_id):
        _, role = require_user_context()
        require_role(role, {"LabIntake"})
        A.get_order(order_id)
        c = A.get_consent(consent_id)
        if c["test_order_id"] != order_id:
            raise err("ERR_CONSENT_NOT_FOUND", "Consent does not belong to order.")
        if c["status"] not in ("DRAFT", "SIGNED"):
            raise err("ERR_INVALID_REQUEST", "Consent cannot be revoked from its state.")
        c["status"] = "REVOKED"
        store.touch(c)
        return success(S.consent(c), 200)

    # ===================================================================
    # Specimen + accession (PRD 3.4)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/specimens", methods=["POST"])
    def create_specimen(order_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        A.get_order(order_id)
        body = get_json_body()
        require_fields(body, ["specimen_type", "collected_at", "quantity_ng"])
        stype = require_enum(body, "specimen_type", A.SPECIMEN_TYPES)
        collected_at = body["collected_at"]
        parse_iso(collected_at, "collected_at")
        quantity = require_number(body, "quantity_ng")
        if quantity < 0:
            raise err("ERR_INVALID_REQUEST", "quantity_ng must be non-negative.")
        sp = {
            "test_order_id": order_id,
            "specimen_type": stype,
            "collected_at": collected_at,
            "received_at": None,
            "quantity_ng": quantity,
            "status": "RECEIVED",
            "superseded_by_specimen_id": None,
        }
        store.stamp_common(sp)
        store.specimens[sp["id"]] = sp
        return success(S.specimen(sp), 201)

    @app.route("/lab/test-orders/<order_id>/specimens", methods=["GET"])
    def list_order_specimens(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [s for s in store.specimens.values() if s["test_order_id"] == order_id]
        status = request.args.get("status")
        if status is not None:
            items = [s for s in items if s["status"] == status]
        page, pag = paginate(items)
        return success([S.specimen(s) for s in page], 200, pagination=pag)

    @app.route("/lab/specimens/<specimen_id>", methods=["GET"])
    def get_specimen_route(specimen_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.specimen(A.get_specimen(specimen_id)), 200)

    @app.route("/lab/specimens", methods=["GET"])
    def list_specimens():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.specimens.values())
        for key in ("test_order_id", "superseded_by_specimen_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [s for s in items if s[key] == val]
        page, pag = paginate(items)
        return success([S.specimen(s) for s in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/specimens/<specimen_id>/accession", methods=["POST"])
    def accession_specimen(order_id, specimen_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        order = A.get_order(order_id)
        sp = A.get_specimen(specimen_id)
        if sp["test_order_id"] != order_id:
            raise err("ERR_SPECIMEN_NOT_FOUND", "Specimen does not belong to order.")
        # State preconditions.
        if order["pipeline_status"] != "REQUISITIONED":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in REQUISITIONED status.")
        if sp["status"] != "RECEIVED":
            raise err("ERR_SPECIMEN_BAD_STATE", "Specimen is not in RECEIVED status.")
        # Consent requirement (only relevant on the sufficient branch path; PRD
        # 3.4 says it is enforced at accessioning). Enforced before QNS screen.
        if order["report_required_consent"]:
            has_signed = any(
                c["test_order_id"] == order_id and c["status"] == "SIGNED"
                for c in store.consents.values()
            )
            if not has_signed:
                raise err("ERR_CONSENT_REQUIRED", "A SIGNED consent is required before accessioning.")
        # QNS screen.
        if qns_sufficient(sp["specimen_type"], sp["quantity_ng"]):
            sp["received_at"] = store.now()
            sp["status"] = "ACCESSIONED"
            store.touch(sp)
            order["pipeline_status"] = "ACCESSIONED"
            store.touch(order)
            # Supersede any prior QNS_REJECTED specimen on the same order.
            for other in store.specimens.values():
                if (
                    other["id"] != sp["id"]
                    and other["test_order_id"] == order_id
                    and other["status"] == "QNS_REJECTED"
                ):
                    other["status"] = "SUPERSEDED"
                    other["superseded_by_specimen_id"] = sp["id"]
                    store.touch(other)
        else:
            sp["status"] = "QNS_REJECTED"
            store.touch(sp)
            # Order stays REQUISITIONED. Recorded outcome, not an error.
        return success(S.specimen(sp), 200)

    # ===================================================================
    # Sequencing start (PRD 3.5)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/sequencing/start", methods=["POST"])
    def start_sequencing(order_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        order = A.get_order(order_id)
        if order["pipeline_status"] != "ACCESSIONED":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in ACCESSIONED status.")
        order["pipeline_status"] = "SEQUENCING"
        store.touch(order)
        return success(S.test_order(order), 200)

    # ===================================================================
    # Variants (PRD 3.5)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/variants", methods=["POST"])
    def create_variant(order_id):
        _, role = require_user_context()
        require_role(role, {"MolecularTechnologist"})
        order = A.get_order(order_id)
        # PRD 3.5: variant calling happens while the order is in SEQUENCING.
        # Calling from any other pipeline state is not a defined transition
        # (PRD 2.8 bad-state family) -> ERR_ORDER_BAD_PIPELINE_STATE.
        if order["pipeline_status"] != "SEQUENCING":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in SEQUENCING status.")
        body = get_json_body()
        require_fields(body, ["gene_id", "hgvs"])
        gene_id = require_string(body, "gene_id")
        hgvs = require_string(body, "hgvs")
        gene = A.get_gene(gene_id)
        included = A.panel_included_gene_ids(order["panel_id"])
        on_panel = gene_id in included
        is_acmg = bool(gene.get("is_acmg_reportable"))
        if not on_panel and not is_acmg:
            raise err("ERR_GENE_NOT_ON_PANEL", "Gene is neither on the panel nor ACMG-reportable.")
        is_incidental = (not on_panel) and is_acmg
        v = {
            "test_order_id": order_id,
            "gene_id": gene_id,
            "hgvs": hgvs,
            "is_incidental": is_incidental,
            "classification": "UNCLASSIFIED",
            "classified_by_user_id": None,
        }
        store.stamp_common(v)
        store.variants[v["id"]] = v
        return success(S.variant(v), 201)

    @app.route("/lab/test-orders/<order_id>/variants", methods=["GET"])
    def list_order_variants(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [v for v in store.variants.values() if v["test_order_id"] == order_id]
        for key in ("classification", "gene_id"):
            val = request.args.get(key)
            if val is not None:
                items = [v for v in items if v[key] == val]
        page, pag = paginate(items)
        return success([S.variant(v) for v in page], 200, pagination=pag)

    @app.route("/lab/variants/<variant_id>", methods=["GET"])
    def get_variant_route(variant_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.variant(A.get_variant(variant_id)), 200)

    @app.route("/lab/variants", methods=["GET"])
    def list_variants():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.variants.values())
        for key in ("test_order_id", "gene_id", "classification"):
            val = request.args.get(key)
            if val is not None:
                items = [v for v in items if v[key] == val]
        page, pag = paginate(items)
        return success([S.variant(v) for v in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/variants/<variant_id>/classify", methods=["POST"])
    def classify_variant(order_id, variant_id):
        user_id, role = require_user_context()
        require_role(role, {"MolecularTechnologist"})
        order = A.get_order(order_id)
        v = A.get_variant(variant_id)
        if v["test_order_id"] != order_id:
            raise err("ERR_VARIANT_NOT_FOUND", "Variant does not belong to order.")
        # State gate: initial classification only from SEQUENCING; reclassification
        # (variant already classified) allowed from SEQUENCING or CLASSIFIED.
        current = v["classification"]
        if current == "UNCLASSIFIED":
            if order["pipeline_status"] != "SEQUENCING":
                raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in SEQUENCING status.")
        else:
            if order["pipeline_status"] not in ("SEQUENCING", "CLASSIFIED"):
                raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in SEQUENCING or CLASSIFIED status.")
        body = get_json_body()
        require_fields(body, ["classification"])
        classification = body["classification"]
        if classification not in A.ACMG_TIERS:
            raise err("ERR_INVALID_CLASSIFICATION", "Classification must be one of the five ACMG tiers.")
        v["classification"] = classification
        v["classified_by_user_id"] = user_id
        store.touch(v)
        A.recompute_pathogenicity(order)
        return success(S.variant(v), 200)

    @app.route("/lab/test-orders/<order_id>/classification/complete", methods=["POST"])
    def complete_classification(order_id):
        _, role = require_user_context()
        require_role(role, {"MolecularTechnologist"})
        order = A.get_order(order_id)
        if order["pipeline_status"] != "SEQUENCING":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in SEQUENCING status.")
        for v in A.order_variants(order_id):
            if v["classification"] == "UNCLASSIFIED":
                raise err("ERR_UNCLASSIFIED_VARIANTS_EXIST", "An UNCLASSIFIED variant remains.")
        order["pipeline_status"] = "CLASSIFIED"
        store.touch(order)
        A.recompute_pathogenicity(order)
        return success(S.test_order(order), 200)

    # ===================================================================
    # Reports (PRD 3.8, 3.9)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/reports", methods=["POST"])
    def create_report(order_id):
        _, role = require_user_context()
        require_role(role, {"LabDirector", "MolecularTechnologist"})
        order = A.get_order(order_id)
        if order["pipeline_status"] != "CLASSIFIED":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in CLASSIFIED status.")
        r = {
            "test_order_id": order_id,
            "reportable_variant_ids": [],
            "incidental_disclosed": False,
            "signed_out_by_user_id": None,
            "amends_report_id": None,
            "status": "DRAFT",
        }
        store.stamp_common(r)
        store.reports[r["id"]] = r
        return success(S.report(r), 201)

    @app.route("/lab/test-orders/<order_id>/reports", methods=["GET"])
    def list_order_reports(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [r for r in store.reports.values() if r["test_order_id"] == order_id]
        status = request.args.get("status")
        if status is not None:
            items = [r for r in items if r["status"] == status]
        page, pag = paginate(items)
        return success([S.report(r) for r in page], 200, pagination=pag)

    @app.route("/lab/reports/<report_id>", methods=["GET"])
    def get_report_route(report_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.report(A.get_report(report_id)), 200)

    @app.route("/lab/reports", methods=["GET"])
    def list_reports():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.reports.values())
        for key in ("test_order_id", "amends_report_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        page, pag = paginate(items)
        return success([S.report(r) for r in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/reports/<report_id>/sign-out", methods=["POST"])
    def sign_out_report(order_id, report_id):
        user_id, role = require_user_context()
        require_role(role, {"LabDirector"})
        order = A.get_order(order_id)
        report = A.get_report(report_id)
        if report["test_order_id"] != order_id:
            raise err("ERR_REPORT_NOT_FOUND", "Report does not belong to order.")
        # Sign-out preconditions in pinned order (PRD 3.8).
        # 1. Pipeline state.
        if order["pipeline_status"] != "CLASSIFIED":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in CLASSIFIED status.")
        # 2. Report state.
        if report["status"] != "DRAFT":
            raise err("ERR_REPORT_BAD_STATE", "Report is not in DRAFT status.")
        # 3. Billing cleared.
        if order["financial_status"] not in ("AUTH_APPROVED", "PATIENT_PAY", "SETTLED"):
            raise err("ERR_BILLING_NOT_CLEARED", "Financial status is not cleared for sign-out.")
        # 4. Segregation of duties.
        for v in A.order_variants(order_id):
            if v.get("classified_by_user_id") == user_id:
                raise err("ERR_SEGREGATION_OF_DUTIES", "Signer also classified a variant on the order.")
        # 5. VUS handling.
        has_vus = any(v["classification"] == "VUS" for v in A.order_variants(order_id))
        if has_vus:
            has_referral = any(
                ref["test_order_id"] == order_id
                and ref["reason"] == "VUS_FOLLOWUP"
                and ref["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED")
                for ref in store.referrals.values()
            )
            if not has_referral:
                raise err("ERR_VUS_REFERRAL_REQUIRED", "A VUS_FOLLOWUP referral is required.")
        # Reportability + incidental disclosure.
        reportable_ids, incidental_disclosed = A.reportability_selection(order)
        report["reportable_variant_ids"] = reportable_ids
        report["incidental_disclosed"] = incidental_disclosed
        report["status"] = "SIGNED_OUT"
        report["signed_out_by_user_id"] = user_id
        store.touch(report)
        order["pipeline_status"] = "SIGNED_OUT"
        # has_reportable_incidental if any disclosed incidental variant.
        if incidental_disclosed:
            order["has_reportable_incidental"] = True
        # Final patient responsibility.
        billing = A.billing_for_order(order_id)
        payer = A.order_payer(order)
        base = billing.get("allowed_amount_cents") if billing else None
        if payer is not None and base is not None:
            order["final_patient_responsibility_cents"] = patient_responsibility_final(
                base, payer, incidental_disclosed
            )
        store.touch(order)
        # If financial_status was AUTH_APPROVED, advance to PATIENT_PAY.
        if order["financial_status"] == "AUTH_APPROVED" and billing is not None:
            billing["status"] = "PATIENT_PAY"
            store.touch(billing)
            order["financial_status"] = "PATIENT_PAY"
            store.touch(order)
        return success(S.report(report), 200)

    @app.route("/lab/test-orders/<order_id>/reports/<report_id>/amend", methods=["POST"])
    def amend_report(order_id, report_id):
        user_id, role = require_user_context()
        require_role(role, {"LabDirector"})
        order = A.get_order(order_id)
        report = A.get_report(report_id)
        if report["test_order_id"] != order_id:
            raise err("ERR_REPORT_NOT_FOUND", "Report does not belong to order.")
        body = get_json_body()
        # OCC guard checked first (PRD 2.7), before business preconditions.
        require_fields(body, ["expected_test_order_version"])
        expected = body["expected_test_order_version"]
        if isinstance(expected, bool) or not isinstance(expected, int):
            raise err("ERR_INVALID_REQUEST", "expected_test_order_version must be an integer.")
        if expected != order["version"]:
            raise err("ERR_STALE_ORDER_VERSION", "Stale test-order version.")
        # State precondition.
        if report["status"] != "SIGNED_OUT":
            raise err("ERR_REPORT_BAD_STATE", "Report is not in SIGNED_OUT status.")
        # Snapshot prior reportable set classifications, keyed by variant id.
        prior_classifications = {}
        for vid in report.get("reportable_variant_ids", []):
            v = store.variants.get(vid)
            if v is not None:
                prior_classifications[vid] = v.get("classification")
        # Recompute reportability for the successor.
        reportable_ids, incidental_disclosed = A.reportability_selection(order)
        successor = {
            "test_order_id": order_id,
            "reportable_variant_ids": reportable_ids,
            "incidental_disclosed": incidental_disclosed,
            "signed_out_by_user_id": user_id,
            "amends_report_id": report["id"],
            "status": "SIGNED_OUT",
        }
        store.stamp_common(successor)
        store.reports[successor["id"]] = successor
        # Prior report -> AMENDED.
        report["status"] = "AMENDED"
        store.touch(report)
        # Variants whose classification differs from the prior report: archive to
        # RECLASSIFIED then re-set to the new (current) classification value.
        for vid, prior_cls in prior_classifications.items():
            v = store.variants.get(vid)
            if v is None:
                continue
            if v.get("classification") != prior_cls:
                new_cls = v["classification"]
                v["classification"] = "RECLASSIFIED"
                store.touch(v)
                v["classification"] = new_cls
                store.touch(v)
        # Increment order version.
        store.touch(order)
        return success(S.report(successor), 201)

    # ===================================================================
    # Billing (PRD 3.6)
    # ===================================================================
    @app.route("/lab/test-orders/<order_id>/billing", methods=["GET"])
    def list_order_billing(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [b for b in store.billings.values() if b["test_order_id"] == order_id]
        page, pag = paginate(items)
        return success([S.billing(b) for b in page], 200, pagination=pag)

    @app.route("/lab/billings/<billing_id>", methods=["GET"])
    def get_billing_route(billing_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.billing(A.get_billing_by_id(billing_id)), 200)

    @app.route("/lab/billings", methods=["GET"])
    def list_billings():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.billings.values())
        for key in ("test_order_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [b for b in items if b[key] == val]
        page, pag = paginate(items)
        return success([S.billing(b) for b in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/billing/auth-decision", methods=["POST"])
    def auth_decision(order_id):
        _, role = require_user_context()
        require_role(role, {"BillingSpecialist"})
        order = A.get_order(order_id)
        billing = A.billing_for_order(order_id)
        if billing is None or billing["status"] != "AUTH_REQUESTED":
            raise err("ERR_BILLING_BAD_STATE", "Billing is not in AUTH_REQUESTED status.")
        body = get_json_body()
        require_fields(body, ["decision"])
        decision = body["decision"]
        if decision not in A.AUTH_DECISIONS:
            raise err("ERR_INVALID_REQUEST", "decision must be APPROVED or DENIED.")
        if decision == "APPROVED":
            allowed = body.get("allowed_amount_cents")
            if (
                allowed is None
                or isinstance(allowed, bool)
                or not isinstance(allowed, int)
                or allowed < 0
                or allowed > order["list_price_cents"]
            ):
                raise err("ERR_ALLOWED_AMOUNT_INVALID", "allowed_amount_cents missing or out of range.")
            billing["allowed_amount_cents"] = allowed
            billing["status"] = "AUTH_APPROVED"
            store.touch(billing)
            order["financial_status"] = "AUTH_APPROVED"
            A.recompute_estimate(order, billing)
            store.touch(order)
        else:
            billing["status"] = "AUTH_DENIED"
            store.touch(billing)
            order["financial_status"] = "AUTH_DENIED"
            store.touch(order)
        return success(S.billing(billing), 200)

    @app.route("/lab/test-orders/<order_id>/billing/convert-self-pay", methods=["POST"])
    def convert_self_pay(order_id):
        _, role = require_user_context()
        require_role(role, {"BillingSpecialist"})
        order = A.get_order(order_id)
        billing = A.billing_for_order(order_id)
        if billing is None or billing["status"] != "AUTH_DENIED":
            raise err("ERR_BILLING_BAD_STATE", "Billing is not in AUTH_DENIED status.")
        billing["writeoff_cents"] = (billing.get("writeoff_cents") or 0) + (billing.get("allowed_amount_cents") or 0)
        billing["allowed_amount_cents"] = order["list_price_cents"]
        billing["status"] = "PATIENT_PAY"
        store.touch(billing)
        order["financial_status"] = "PATIENT_PAY"
        A.recompute_estimate(order, billing)
        store.touch(order)
        return success(S.billing(billing), 200)

    @app.route("/lab/test-orders/<order_id>/billing/collect", methods=["POST"])
    def collect(order_id):
        _, role = require_user_context()
        require_role(role, {"BillingSpecialist"})
        order = A.get_order(order_id)
        billing = A.billing_for_order(order_id)
        if billing is None or billing["status"] != "PATIENT_PAY":
            raise err("ERR_BILLING_BAD_STATE", "Billing is not in PATIENT_PAY status.")
        body = get_json_body()
        require_fields(body, ["amount_cents"])
        amount = body["amount_cents"]
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            raise err("ERR_INVALID_REQUEST", "amount_cents must be a non-negative integer.")
        # Owed = final after sign-out, else estimate.
        report_signed = any(
            r["test_order_id"] == order_id and r["status"] == "SIGNED_OUT"
            for r in store.reports.values()
        )
        if report_signed:
            owed = order.get("final_patient_responsibility_cents")
        else:
            owed = order.get("estimated_patient_responsibility_cents")
        if amount != owed:
            raise err("ERR_COLLECT_AMOUNT_MISMATCH", "Collected amount does not match the amount owed.")
        billing["coinsurance_collected_cents"] = (billing.get("coinsurance_collected_cents") or 0) + amount
        billing["status"] = "SETTLED"
        store.touch(billing)
        order["financial_status"] = "SETTLED"
        store.touch(order)
        return success(S.billing(billing), 200)

    # ===================================================================
    # Sequencers + runs (PRD 3.5, 3.12)
    # ===================================================================
    @app.route("/lab/sequencers", methods=["POST"])
    def create_sequencer():
        _, role = require_user_context()
        require_role(role, {"LabDirector"})
        body = get_json_body()
        require_fields(body, ["instrument_name"])
        name = require_string(body, "instrument_name")
        buffer = body.get("turnaround_buffer_minutes", 60)
        if isinstance(buffer, bool) or not isinstance(buffer, int) or buffer < 0:
            raise err("ERR_INVALID_REQUEST", "turnaround_buffer_minutes must be a non-negative integer.")
        for s in store.sequencers.values():
            if s["instrument_name"] == name:
                raise err("ERR_INVALID_REQUEST", "instrument_name must be unique.")
        s = {
            "instrument_name": name,
            "turnaround_buffer_minutes": buffer,
            "status": "ONLINE",
        }
        store.stamp_common(s)
        store.sequencers[s["id"]] = s
        return success(S.sequencer(s), 201)

    @app.route("/lab/sequencers", methods=["GET"])
    def list_sequencers():
        _, role = require_user_context()
        require_role(role, ALL)
        page, pag = paginate(list(store.sequencers.values()))
        return success([S.sequencer(s) for s in page], 200, pagination=pag)

    @app.route("/lab/sequencers/<sequencer_id>", methods=["GET"])
    def get_sequencer_route(sequencer_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.sequencer(A.get_sequencer(sequencer_id)), 200)

    @app.route("/lab/sequencers/<sequencer_id>/runs", methods=["POST"])
    def schedule_run(sequencer_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        seq = A.get_sequencer(sequencer_id)
        body = get_json_body()
        require_fields(body, ["test_order_id", "window_start", "window_end"])
        test_order_id = require_string(body, "test_order_id")
        window_start = body["window_start"]
        window_end = body["window_end"]
        ws = parse_iso(window_start, "window_start")
        we = parse_iso(window_end, "window_end")
        # Referenced order must exist.
        A.get_order(test_order_id)
        # window_end strictly after window_start.
        if not (we > ws):
            raise err("ERR_INVALID_REQUEST", "window_end must be strictly after window_start.")
        # Overlap (closed + buffer) against SCHEDULED/RUNNING runs on same sequencer.
        buffer = seq["turnaround_buffer_minutes"]
        for other in store.sequencer_runs.values():
            if other["sequencer_id"] != sequencer_id:
                continue
            if other["status"] not in ("SCHEDULED", "RUNNING"):
                continue
            if sequencer_runs_conflict(window_start, window_end, other["window_start"], other["window_end"], buffer):
                raise err("ERR_RUN_WINDOW_CONFLICT", "Run window conflicts with another run.")
        run = {
            "sequencer_id": sequencer_id,
            "test_order_id": test_order_id,
            "window_start": window_start,
            "window_end": window_end,
            "status": "SCHEDULED",
        }
        store.stamp_common(run)
        store.sequencer_runs[run["id"]] = run
        return success(S.sequencer_run(run), 201)

    @app.route("/lab/sequencers/<sequencer_id>/runs", methods=["GET"])
    def list_sequencer_runs(sequencer_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_sequencer(sequencer_id)
        items = [r for r in store.sequencer_runs.values() if r["sequencer_id"] == sequencer_id]
        status = request.args.get("status")
        if status is not None:
            items = [r for r in items if r["status"] == status]
        page, pag = paginate(items)
        return success([S.sequencer_run(r) for r in page], 200, pagination=pag)

    @app.route("/lab/sequencer-runs/<run_id>", methods=["GET"])
    def get_run_route(run_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.sequencer_run(A.get_run(run_id)), 200)

    @app.route("/lab/sequencer-runs", methods=["GET"])
    def list_runs():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.sequencer_runs.values())
        for key in ("test_order_id", "sequencer_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        page, pag = paginate(items)
        return success([S.sequencer_run(r) for r in page], 200, pagination=pag)

    @app.route("/lab/sequencers/<sequencer_id>/runs/<run_id>/start", methods=["POST"])
    def start_run(sequencer_id, run_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        A.get_sequencer(sequencer_id)
        run = A.get_run(run_id)
        if run["sequencer_id"] != sequencer_id:
            raise err("ERR_RUN_NOT_FOUND", "Run does not belong to sequencer.")
        if run["status"] != "SCHEDULED":
            raise err("ERR_RUN_BAD_STATE", "Run is not in SCHEDULED status.")
        order = A.get_order(run["test_order_id"])
        if order["pipeline_status"] != "SEQUENCING":
            raise err("ERR_ORDER_BAD_PIPELINE_STATE", "Order is not in SEQUENCING status.")
        run["status"] = "RUNNING"
        store.touch(run)
        return success(S.sequencer_run(run), 200)

    @app.route("/lab/sequencers/<sequencer_id>/runs/<run_id>/finish", methods=["POST"])
    def finish_run(sequencer_id, run_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        A.get_sequencer(sequencer_id)
        run = A.get_run(run_id)
        if run["sequencer_id"] != sequencer_id:
            raise err("ERR_RUN_NOT_FOUND", "Run does not belong to sequencer.")
        if run["status"] != "RUNNING":
            raise err("ERR_RUN_BAD_STATE", "Run is not in RUNNING status.")
        run["status"] = "DONE"
        store.touch(run)
        return success(S.sequencer_run(run), 200)

    @app.route("/lab/sequencers/<sequencer_id>/runs/<run_id>/abort", methods=["POST"])
    def abort_run(sequencer_id, run_id):
        _, role = require_user_context()
        require_role(role, {"AccessioningTech"})
        A.get_sequencer(sequencer_id)
        run = A.get_run(run_id)
        if run["sequencer_id"] != sequencer_id:
            raise err("ERR_RUN_NOT_FOUND", "Run does not belong to sequencer.")
        if run["status"] not in ("SCHEDULED", "RUNNING"):
            raise err("ERR_RUN_BAD_STATE", "Run cannot be aborted from its state.")
        run["status"] = "ABORTED"
        store.touch(run)
        return success(S.sequencer_run(run), 200)

    # ===================================================================
    # Counselor profiles + referrals (PRD 3.11, 3.12)
    # ===================================================================
    @app.route("/lab/counselors", methods=["POST"])
    def create_counselor():
        _, role = require_user_context()
        require_role(role, {"LabDirector"})
        body = get_json_body()
        require_fields(body, ["counselor_name"])
        name = require_string(body, "counselor_name")
        for c in store.counselors.values():
            if c["counselor_name"] == name:
                raise err("ERR_INVALID_REQUEST", "counselor_name must be unique.")
        c = {"counselor_name": name, "status": "ACTIVE"}
        store.stamp_common(c)
        store.counselors[c["id"]] = c
        return success(S.counselor(c), 201)

    @app.route("/lab/counselors", methods=["GET"])
    def list_counselors():
        _, role = require_user_context()
        require_role(role, ALL)
        page, pag = paginate(list(store.counselors.values()))
        return success([S.counselor(c) for c in page], 200, pagination=pag)

    @app.route("/lab/counselors/<counselor_id>", methods=["GET"])
    def get_counselor_route(counselor_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.counselor(A.get_counselor(counselor_id)), 200)

    @app.route("/lab/test-orders/<order_id>/referrals", methods=["POST"])
    def create_referral(order_id):
        _, role = require_user_context()
        require_role(role, {"LabDirector", "MolecularTechnologist", "GeneticCounselor"})
        A.get_order(order_id)
        body = get_json_body()
        require_fields(body, ["counselor_id", "reason"])
        counselor_id = require_string(body, "counselor_id")
        reason = require_enum(body, "reason", A.REFERRAL_REASONS)
        A.get_counselor(counselor_id)
        triggering_variant_id = body.get("triggering_variant_id")
        if triggering_variant_id is not None:
            if not isinstance(triggering_variant_id, str):
                raise err("ERR_INVALID_REQUEST", "triggering_variant_id must be a string.")
            A.get_variant(triggering_variant_id)
        ref = {
            "test_order_id": order_id,
            "counselor_id": counselor_id,
            "triggering_variant_id": triggering_variant_id,
            "reason": reason,
            "slot_start": None,
            "slot_end": None,
            "status": "REQUESTED",
        }
        store.stamp_common(ref)
        store.referrals[ref["id"]] = ref
        return success(S.referral(ref), 201)

    @app.route("/lab/test-orders/<order_id>/referrals", methods=["GET"])
    def list_order_referrals(order_id):
        _, role = require_user_context()
        require_role(role, ALL)
        A.get_order(order_id)
        items = [r for r in store.referrals.values() if r["test_order_id"] == order_id]
        for key in ("status", "reason"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        page, pag = paginate(items)
        return success([S.referral(r) for r in page], 200, pagination=pag)

    @app.route("/lab/referrals/<referral_id>", methods=["GET"])
    def get_referral_route(referral_id):
        _, role = require_user_context()
        require_role(role, ALL)
        return success(S.referral(A.get_referral(referral_id)), 200)

    @app.route("/lab/referrals", methods=["GET"])
    def list_referrals():
        _, role = require_user_context()
        require_role(role, ALL)
        items = list(store.referrals.values())
        for key in ("counselor_id", "triggering_variant_id", "test_order_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [r for r in items if r[key] == val]
        page, pag = paginate(items)
        return success([S.referral(r) for r in page], 200, pagination=pag)

    @app.route("/lab/test-orders/<order_id>/referrals/<referral_id>/schedule", methods=["POST"])
    def schedule_referral(order_id, referral_id):
        _, role = require_user_context()
        require_role(role, {"GeneticCounselor"})
        A.get_order(order_id)
        ref = A.get_referral(referral_id)
        if ref["test_order_id"] != order_id:
            raise err("ERR_REFERRAL_NOT_FOUND", "Referral does not belong to order.")
        if ref["status"] != "REQUESTED":
            raise err("ERR_REFERRAL_BAD_STATE", "Referral is not in REQUESTED status.")
        body = get_json_body()
        require_fields(body, ["slot_start", "slot_end"])
        slot_start = body["slot_start"]
        slot_end = body["slot_end"]
        ss = parse_iso(slot_start, "slot_start")
        se = parse_iso(slot_end, "slot_end")
        if not (se > ss):
            raise err("ERR_INVALID_REQUEST", "slot_end must be strictly after slot_start.")
        # Half-open overlap against SCHEDULED referrals for same counselor.
        for other in store.referrals.values():
            if other["id"] == ref["id"]:
                continue
            if other["counselor_id"] != ref["counselor_id"]:
                continue
            if other["status"] != "SCHEDULED":
                continue
            if other.get("slot_start") is None or other.get("slot_end") is None:
                continue
            if counselor_slots_conflict(slot_start, slot_end, other["slot_start"], other["slot_end"]):
                raise err("ERR_COUNSELOR_SLOT_CONFLICT", "Counselor slot conflicts with another referral.")
        ref["slot_start"] = slot_start
        ref["slot_end"] = slot_end
        ref["status"] = "SCHEDULED"
        store.touch(ref)
        return success(S.referral(ref), 200)

    @app.route("/lab/test-orders/<order_id>/referrals/<referral_id>/complete", methods=["POST"])
    def complete_referral(order_id, referral_id):
        _, role = require_user_context()
        require_role(role, {"GeneticCounselor"})
        A.get_order(order_id)
        ref = A.get_referral(referral_id)
        if ref["test_order_id"] != order_id:
            raise err("ERR_REFERRAL_NOT_FOUND", "Referral does not belong to order.")
        if ref["status"] != "SCHEDULED":
            raise err("ERR_REFERRAL_BAD_STATE", "Referral is not in SCHEDULED status.")
        ref["status"] = "COMPLETED"
        store.touch(ref)
        return success(S.referral(ref), 200)

    @app.route("/lab/test-orders/<order_id>/referrals/<referral_id>/cancel", methods=["POST"])
    def cancel_referral(order_id, referral_id):
        _, role = require_user_context()
        require_role(role, {"GeneticCounselor"})
        A.get_order(order_id)
        ref = A.get_referral(referral_id)
        if ref["test_order_id"] != order_id:
            raise err("ERR_REFERRAL_NOT_FOUND", "Referral does not belong to order.")
        if ref["status"] not in ("REQUESTED", "SCHEDULED"):
            raise err("ERR_REFERRAL_BAD_STATE", "Referral cannot be cancelled from its state.")
        ref["status"] = "CANCELLED"
        store.touch(ref)
        return success(S.referral(ref), 200)
