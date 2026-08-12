"""Registers exactly the (method, path) endpoint pairs declared in SCAFFOLD.yaml."""
from routes import properties, vendors, appraisals, listings, offers, issues, write_downs, \
    closings, extensions, ledger


def register_routes(app):
    add = app.add_url_rule

    # OREO properties
    add("/api/oreo-properties", "create_property", properties.create_property, methods=["POST"])
    add("/api/oreo-properties", "list_properties", properties.list_properties, methods=["GET"])
    add("/api/oreo-properties/<prop_id>", "get_property", properties.get_property, methods=["GET"])
    add("/api/oreo-properties/<prop_id>/summary", "get_summary", properties.get_summary, methods=["GET"])
    add("/api/oreo-properties/<prop_id>/charge-off", "manual_charge_off",
        properties.manual_charge_off, methods=["POST"])
    add("/api/oreo-properties/<prop_id>/broker-recommendation", "broker_recommendation",
        properties.broker_recommendation, methods=["GET"])

    # Carrying costs
    add("/api/carrying-costs", "create_cost", properties.create_cost, methods=["POST"])
    add("/api/carrying-costs", "list_costs", properties.list_costs, methods=["GET"])
    add("/api/carrying-costs/<cost_id>", "get_cost", properties.get_cost, methods=["GET"])

    # Appraisers
    add("/api/appraisers", "create_appraiser", vendors.create_appraiser, methods=["POST"])
    add("/api/appraisers", "list_appraisers", vendors.list_appraisers, methods=["GET"])
    add("/api/appraisers/<entity_id>", "get_appraiser", vendors.get_appraiser, methods=["GET"])

    # Appraisals
    add("/api/appraisals", "create_appraisal", appraisals.create_appraisal, methods=["POST"])
    add("/api/appraisals", "list_appraisals", appraisals.list_appraisals, methods=["GET"])
    add("/api/appraisals/<entity_id>", "get_appraisal", appraisals.get_appraisal, methods=["GET"])
    add("/api/appraisals/<entity_id>/submit", "submit_appraisal",
        appraisals.submit_appraisal, methods=["POST"])
    add("/api/appraisals/<entity_id>/certify", "certify_appraisal",
        appraisals.certify_appraisal, methods=["POST"])
    add("/api/appraisals/<entity_id>/reject", "reject_appraisal",
        appraisals.reject_appraisal, methods=["POST"])

    # Brokers
    add("/api/brokers", "create_broker", vendors.create_broker, methods=["POST"])
    add("/api/brokers", "list_brokers", vendors.list_brokers, methods=["GET"])
    add("/api/brokers/<entity_id>", "get_broker", vendors.get_broker, methods=["GET"])
    add("/api/brokers/<entity_id>", "patch_broker", vendors.patch_broker, methods=["PATCH"])

    # Listing agreements
    add("/api/listing-agreements", "create_listing", listings.create_listing, methods=["POST"])
    add("/api/listing-agreements", "list_listings", listings.list_listings, methods=["GET"])
    add("/api/listing-agreements/<entity_id>", "get_listing", listings.get_listing, methods=["GET"])
    add("/api/listing-agreements/<entity_id>/activate", "activate_listing",
        listings.activate_listing, methods=["POST"])
    add("/api/listing-agreements/<entity_id>/terminate", "terminate_listing",
        listings.terminate_listing, methods=["POST"])

    # Offers
    add("/api/offers", "create_offer", offers.create_offer, methods=["POST"])
    add("/api/offers", "list_offers", offers.list_offers, methods=["GET"])
    add("/api/offers/<entity_id>", "get_offer", offers.get_offer, methods=["GET"])
    add("/api/offers/<entity_id>/submit-review", "submit_review", offers.submit_review, methods=["POST"])
    add("/api/offers/<entity_id>/counter", "counter_offer", offers.counter_offer, methods=["POST"])
    add("/api/offers/<entity_id>/resume", "resume_offer", offers.resume_offer, methods=["POST"])
    add("/api/offers/<entity_id>/accept", "accept_offer", offers.accept_offer, methods=["POST"])
    add("/api/offers/<entity_id>/reject", "reject_offer", offers.reject_offer, methods=["POST"])
    add("/api/offers/<entity_id>/withdraw", "withdraw_offer", offers.withdraw_offer, methods=["POST"])
    add("/api/offers/<entity_id>/rescind", "rescind_offer", offers.rescind_offer, methods=["POST"])

    # Issues
    add("/api/issues", "create_issue", issues.create_issue, methods=["POST"])
    add("/api/issues", "list_issues", issues.list_issues, methods=["GET"])
    add("/api/issues/<entity_id>", "get_issue", issues.get_issue, methods=["GET"])
    add("/api/issues/<entity_id>/start-remediation", "start_remediation",
        issues.start_remediation, methods=["POST"])
    add("/api/issues/<entity_id>/resolve", "resolve_issue", issues.resolve_issue, methods=["POST"])
    add("/api/issues/<entity_id>/waive", "waive_issue", issues.waive_issue, methods=["POST"])

    # Write-downs
    add("/api/write-downs", "create_write_down", write_downs.create_write_down, methods=["POST"])
    add("/api/write-downs", "list_write_downs", write_downs.list_write_downs, methods=["GET"])
    add("/api/write-downs/<entity_id>", "get_write_down", write_downs.get_write_down, methods=["GET"])
    add("/api/write-downs/<entity_id>/approve", "approve_write_down",
        write_downs.approve_write_down, methods=["POST"])
    add("/api/write-downs/<entity_id>/reject", "reject_write_down",
        write_downs.reject_write_down, methods=["POST"])

    # Closing statements
    add("/api/closing-statements", "create_closing", closings.create_closing, methods=["POST"])
    add("/api/closing-statements", "list_closings", closings.list_closings, methods=["GET"])
    add("/api/closing-statements/<entity_id>", "get_closing", closings.get_closing, methods=["GET"])
    add("/api/closing-statements/<entity_id>/settle", "settle_closing",
        closings.settle_closing, methods=["POST"])
    add("/api/closing-statements/<entity_id>/void", "void_closing",
        closings.void_closing, methods=["POST"])

    # Extension requests
    add("/api/extension-requests", "create_extension", extensions.create_extension, methods=["POST"])
    add("/api/extension-requests", "list_extensions", extensions.list_extensions, methods=["GET"])
    add("/api/extension-requests/<entity_id>", "get_extension", extensions.get_extension, methods=["GET"])
    add("/api/extension-requests/<entity_id>/submit", "submit_extension",
        extensions.submit_extension, methods=["POST"])
    add("/api/extension-requests/<entity_id>/approve", "approve_extension",
        extensions.approve_extension, methods=["POST"])
    add("/api/extension-requests/<entity_id>/deny", "deny_extension",
        extensions.deny_extension, methods=["POST"])
    add("/api/extension-requests/<entity_id>/revise", "revise_extension",
        extensions.revise_extension, methods=["POST"])

    # Ledger (append-only, read-only over HTTP)
    add("/api/ledger-entries", "list_ledger", ledger.list_ledger, methods=["GET"])
    add("/api/ledger-entries/<entity_id>", "get_ledger_entry", ledger.get_ledger_entry, methods=["GET"])

    # Approval tiers
    add("/api/approval-tiers", "create_tier", vendors.create_tier, methods=["POST"])
    add("/api/approval-tiers", "list_tiers", vendors.list_tiers, methods=["GET"])

    # Logical clock
    add("/api/_clock/set_current_utc", "set_clock", ledger.set_clock, methods=["POST"])
