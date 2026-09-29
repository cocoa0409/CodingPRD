"""Roles, the endpoint authorisation table and ladder rungs 1-3 (PRD 2.1, 4)."""
from flask import request

import store
from errors import ApiError

PA = "PlantAdmin"
SE = "SalesEngineer"
DE = "DesignEngineer"
CA = "ContractAdmin"
MP = "MaterialsPlanner"
TE = "TestEngineer"
WC = "WitnessCoordinator"
CW = "CustomerWitness"
CR = "CustomerReviewer"
QE = "QualityEngineer"
CO = "ComplianceOfficer"
LC = "LogisticsCoordinator"
FS = "FieldServiceEngineer"

ROLES = {PA, SE, DE, CA, MP, TE, WC, CW, CR, QE, CO, LC, FS}

_ALL12 = [PA, SE, CA, DE, MP, TE, WC, CR, QE, CO, LC, FS]
_ALL13 = _ALL12 + [CW]

ENDPOINT_ROLES = {
    "POST /_clock/set_current_utc": [PA],
    # Engineered orders
    "POST /engineered-orders": [SE, CA, PA],
    "GET /engineered-orders": _ALL12,
    "GET /engineered-orders/{id}": _ALL13,
    "PATCH /engineered-orders/{id}": [CA, PA],
    "POST /engineered-orders/{id}/start-production": [MP],
    "POST /engineered-orders/{id}/close-engineering": [DE, PA],
    "POST /engineered-orders/{id}/cancel": [CA, PA],
    "GET /engineered-orders/{id}/posture": [PA, MP, QE, LC, CA],
    "GET /engineered-orders/{id}/financial-summary": [CA, SE, PA],
    # Submittal drawings
    "POST /engineered-orders/{id}/submittal-drawings": [DE],
    "GET /engineered-orders/{id}/submittal-drawings": [PA, DE, CR, CO, QE, CA],
    "GET /submittal-drawings": [PA, DE, CR, CO, QE],
    "GET /submittal-drawings/{id}": [PA, DE, CR, CO, QE, CA],
    "POST /submittal-drawings/{id}/submit": [DE],
    "POST /submittal-drawings/{id}/begin-review": [CR],
    "POST /submittal-drawings/{id}/disposition": [CR],
    # Escalation clauses
    "POST /engineered-orders/{id}/escalation-clauses": [CA],
    "GET /engineered-orders/{id}/escalation-clauses": [CA, SE, PA, CR],
    "GET /escalation-clauses/{id}": [CA, SE, PA, CR],
    # Commodity index points
    "POST /commodity-index-points": [CA, PA],
    "GET /commodity-index-points": [CA, PA, SE, CR],
    "GET /commodity-index-points/{id}": [CA, PA, SE, CR],
    "PATCH /commodity-index-points/{id}": [CA, PA],
    # Escalation adjustments
    "POST /engineered-orders/{id}/escalation-adjustments": [CA],
    "GET /escalation-adjustments": [CA, SE, PA, CR],
    "GET /escalation-adjustments/{id}": [CA, SE, PA, CR],
    "POST /escalation-adjustments/{id}/submit": [CA],
    "POST /escalation-adjustments/{id}/accept": [CR],
    "POST /escalation-adjustments/{id}/dispute": [CR],
    "POST /escalation-adjustments/{id}/recalculate": [CA],
    "POST /escalation-adjustments/{id}/withdraw": [CA],
    # Suppliers
    "POST /suppliers": [PA, QE],
    "GET /suppliers": [PA, QE, MP, CO],
    "GET /suppliers/{id}": [PA, QE, MP, CO],
    "POST /suppliers/{id}/receipt-events": [MP, QE],
    "POST /suppliers/{id}/suspend": [PA],
    "GET /suppliers/{id}/quality-summary": [PA, QE, MP],
    # Long lead components
    "POST /suppliers/{id}/long-lead-components": [MP, PA],
    "GET /suppliers/{id}/long-lead-components": [MP, PA, QE],
    "GET /long-lead-components": [MP, PA, QE, CO],
    "GET /long-lead-components/{id}": [MP, PA, QE, CO],
    "POST /long-lead-components/{id}/receipts": [MP],
    "POST /long-lead-components/{id}/release-quarantine": [QE],
    "POST /long-lead-components/{id}/obsolete": [PA, MP],
    # Component allocations
    "POST /component-allocations": [MP],
    "GET /component-allocations": [MP, PA, QE, CA],
    "GET /component-allocations/{id}": [MP, PA, QE, CA],
    "POST /component-allocations/{id}/commit": [MP],
    "POST /component-allocations/{id}/release": [MP],
    # Test bays
    "POST /test-bays": [PA, TE],
    "GET /test-bays": [PA, TE, WC, QE],
    "GET /test-bays/{id}": [PA, TE, WC, QE],
    "PATCH /test-bays/{id}": [PA],
    "GET /test-bays/{id}/schedule": [PA, TE, WC],
    # Factory acceptance tests
    "POST /factory-acceptance-tests": [TE, QE],
    "GET /factory-acceptance-tests": [PA, TE, QE, WC, CW, CO, CA],
    "GET /factory-acceptance-tests/{id}": [PA, TE, QE, WC, CW, CO, CA],
    "POST /factory-acceptance-tests/{id}/schedule": [TE],
    "POST /factory-acceptance-tests/{id}/start": [TE],
    "POST /factory-acceptance-tests/{id}/conclude": [TE, QE],
    "POST /factory-acceptance-tests/{id}/abandon": [TE, PA],
    # Witness parties
    "POST /witness-parties": [WC, PA],
    "GET /witness-parties": [WC, PA, TE, QE],
    "GET /witness-parties/{id}": [WC, PA, TE, QE, CW],
    "PATCH /witness-parties/{id}": [WC, PA],
    "GET /witness-parties/{id}/load": [WC, PA, TE],
    # Witness assignments
    "POST /factory-acceptance-tests/{id}/witness-assignments": [WC],
    "GET /factory-acceptance-tests/{id}/witness-assignments": [WC, TE, PA, QE, CW],
    "GET /witness-assignments": [WC, TE, PA, QE, CW],
    "GET /witness-assignments/{id}": [WC, TE, PA, QE, CW],
    "POST /witness-assignments/{id}/confirm": [CW, WC],
    "POST /witness-assignments/{id}/decline": [CW, WC],
    "POST /witness-assignments/{id}/reinvite": [WC],
    "POST /witness-assignments/{id}/waive": [WC, PA],
    # Test reports
    "POST /factory-acceptance-tests/{id}/test-reports": [TE],
    "GET /factory-acceptance-tests/{id}/test-reports": [TE, QE, CO, PA, CW, CR],
    "GET /test-reports/{id}": [TE, QE, CO, PA, CW, CR],
    "POST /test-reports/{id}/issue": [QE],
    # Compliance labels
    "POST /engineered-orders/{id}/compliance-labels": [CO],
    "GET /engineered-orders/{id}/compliance-labels": [CO, QE, PA, LC, CR],
    "GET /compliance-labels": [CO, QE, PA, LC],
    "GET /compliance-labels/{id}": [CO, QE, PA, LC, CR],
    "POST /compliance-labels/{id}/generate": [CO],
    "POST /compliance-labels/{id}/verify": [QE],
    "POST /compliance-labels/{id}/issue": [CO],
    "POST /compliance-labels/{id}/void": [CO, QE],
    # Shipment releases
    "POST /engineered-orders/{id}/shipment-releases": [LC, CA],
    "GET /engineered-orders/{id}/shipment-releases": [LC, CA, PA, FS, SE],
    "GET /shipment-releases/{id}": [LC, CA, PA, FS, SE],
    "POST /shipment-releases/{id}/clear": [LC],
    "POST /shipment-releases/{id}/stage": [LC],
    "POST /shipment-releases/{id}/ship": [LC],
    "POST /shipment-releases/{id}/deliver": [LC, FS],
    # Site storage agreements
    "POST /shipment-releases/{id}/site-storage-agreements": [LC],
    "GET /shipment-releases/{id}/site-storage-agreements": [LC, CA, PA, SE],
    "GET /site-storage-agreements/{id}": [LC, CA, PA, SE],
    "POST /site-storage-agreements/{id}/close": [LC],
    "POST /site-storage-agreements/{id}/waive": [LC, CA],
    # Commissioning jobs
    "POST /engineered-orders/{id}/commissioning-jobs": [FS, PA],
    "GET /commissioning-jobs": [FS, PA, QE, LC, CA, CR],
    "GET /commissioning-jobs/{id}": [FS, PA, QE, LC, CA, CR],
    "POST /commissioning-jobs/{id}/mobilize": [FS],
    "POST /commissioning-jobs/{id}/request-energization": [FS],
    "POST /commissioning-jobs/{id}/energize": [FS, QE],
    "POST /commissioning-jobs/{id}/demobilize": [FS],
    "POST /commissioning-jobs/{id}/cancel": [PA, FS],
    # Punch list items
    "POST /commissioning-jobs/{id}/punch-list-items": [FS, QE, CR],
    "GET /commissioning-jobs/{id}/punch-list-items": [FS, QE, PA, CR, CA],
    "GET /punch-list-items/{id}": [FS, QE, PA, CR, CA],
    "POST /punch-list-items/{id}/assign": [FS],
    "POST /punch-list-items/{id}/resolve": [FS],
    "POST /punch-list-items/{id}/close": [QE, CR],
    "POST /punch-list-items/{id}/reject": [QE, CR],
    # Warranty claims
    "POST /engineered-orders/{id}/warranty-claims": [CA, FS, CR],
    "GET /warranty-claims": [CA, QE, PA, FS, CR, MP],
    "GET /warranty-claims/{id}": [CA, QE, PA, FS, CR, MP],
    "POST /warranty-claims/{id}/issue-rma": [CA, QE],
    "POST /warranty-claims/{id}/receive-unit": [QE, MP],
    "POST /warranty-claims/{id}/settle": [CA],
    "POST /warranty-claims/{id}/reject": [CA, QE],
    # Failure analysis reports
    "POST /warranty-claims/{id}/failure-analysis-reports": [QE],
    "GET /warranty-claims/{id}/failure-analysis-reports": [QE, CA, PA, MP],
    "GET /failure-analysis-reports": [QE, CA, PA, MP],
    "GET /failure-analysis-reports/{id}": [QE, CA, PA, MP],
    "POST /failure-analysis-reports/{id}/publish": [QE],
    "POST /failure-analysis-reports/{id}/retract": [QE, PA],
}


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_witness(self):
        return self.role == CW


def authenticate(endpoint_key):
    """Rungs 1-3: header presence, role recognition (incl. entity-backed
    resolution), endpoint role permission."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or str(uid).strip() == "" or role is None or str(role).strip() == "":
        raise ApiError("ERR_MISSING_AUTH_HEADER", "X-User-ID and X-User-Role are required")
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE", "unrecognised role: %s" % role)
    if role == CW and store.get("party", uid) is None:
        raise ApiError("ERR_UNKNOWN_ROLE", "CustomerWitness identity does not resolve to a witness party")
    allowed = ENDPOINT_ROLES.get(endpoint_key)
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED", "%s may not call %s" % (role, endpoint_key))
    return Actor(uid, role)


def check_order_ownership(actor, order):
    """Rung 4: SalesEngineer order-scoped write ownership."""
    if actor.role != SE or order is None:
        return
    if order.get("owning_sales_user_id") != actor.user_id:
        raise ApiError("ERR_NOT_ORDER_OWNER", "acting user does not own this order")


def check_sod(actor, other_user_id):
    """Rung 5: segregation of duties."""
    if other_user_id is not None and actor.user_id == other_user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", "acting user performed the paired upstream step")


def check_witness_identity(actor, witness_party_id):
    """Rung 6: CustomerWitness identity."""
    if actor.role == CW and actor.user_id != witness_party_id:
        raise ApiError("ERR_WITNESS_IDENTITY_MISMATCH", "witness party mismatch")
