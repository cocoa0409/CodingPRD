"""Existence resolution (PRD sections 2.5 / 2.6 step 6).

Path identifiers resolve strictly left to right; only once they have all
resolved does the server look at foreign keys carried in the request body, in
the order the endpoint declares them.
"""

import db
from errors import ApiError

_NOT_FOUND = {
    "chassis_model": "ERR_CHASSIS_MODEL_NOT_FOUND",
    "body_spec": "ERR_BODY_SPEC_NOT_FOUND",
    "equipment_spec": "ERR_EQUIPMENT_SPEC_NOT_FOUND",
    "work_bay": "ERR_WORK_BAY_NOT_FOUND",
    "customer": "ERR_CUSTOMER_NOT_FOUND",
    "build_configuration": "ERR_BUILD_CONFIGURATION_NOT_FOUND",
    "chassis": "ERR_CHASSIS_NOT_FOUND",
    "upfit_order": "ERR_UPFIT_ORDER_NOT_FOUND",
    "equipment_installation": "ERR_EQUIPMENT_INSTALLATION_NOT_FOUND",
    "electrical_interface": "ERR_ELECTRICAL_INTERFACE_NOT_FOUND",
    "build_slot": "ERR_BUILD_SLOT_NOT_FOUND",
    "weight_certification": "ERR_WEIGHT_CERTIFICATION_NOT_FOUND",
    "compliance_label": "ERR_COMPLIANCE_LABEL_NOT_FOUND",
    "warranty_claim": "ERR_WARRANTY_CLAIM_NOT_FOUND",
}

_LABELS = {
    "chassis_model": "Chassis model",
    "body_spec": "Body specification",
    "equipment_spec": "Equipment specification",
    "work_bay": "Work bay",
    "customer": "Customer",
    "build_configuration": "Build configuration",
    "chassis": "Chassis",
    "upfit_order": "Upfit order",
    "equipment_installation": "Equipment installation",
    "electrical_interface": "Electrical interface",
    "build_slot": "Build slot",
    "weight_certification": "Weight certification",
    "compliance_label": "Compliance label",
    "warranty_claim": "Warranty claim",
}


def find(kind, row_id):
    """Return the row or None."""
    collection = db.COLLECTIONS[kind]
    if row_id is None or not isinstance(row_id, str):
        return None
    return collection.get(row_id)


def must(kind, row_id):
    row = find(kind, row_id)
    if row is None:
        raise ApiError(
            _NOT_FOUND[kind],
            "%s '%s' does not exist." % (_LABELS[kind], row_id),
        )
    return row


def chassis_model(row_id):
    return must("chassis_model", row_id)


def body_spec(row_id):
    return must("body_spec", row_id)


def equipment_spec(row_id):
    return must("equipment_spec", row_id)


def work_bay(row_id):
    return must("work_bay", row_id)


def customer(row_id):
    return must("customer", row_id)


def build_configuration(row_id):
    return must("build_configuration", row_id)


def chassis(row_id):
    return must("chassis", row_id)


def upfit_order(row_id):
    return must("upfit_order", row_id)


def equipment_installation(row_id):
    return must("equipment_installation", row_id)


def electrical_interface(row_id):
    return must("electrical_interface", row_id)


def build_slot(row_id):
    return must("build_slot", row_id)


def weight_certification(row_id):
    return must("weight_certification", row_id)


def compliance_label(row_id):
    return must("compliance_label", row_id)


def warranty_claim(row_id):
    return must("warranty_claim", row_id)


# --------------------------------------------------------------------------
# Child collection helpers
# --------------------------------------------------------------------------
def installations_of(order_id):
    return sorted(
        [r for r in db.equipment_installations.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def interfaces_of(order_id):
    return sorted(
        [r for r in db.electrical_interfaces.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def slots_of(order_id):
    return sorted(
        [r for r in db.build_slots.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def slots_in_bay(bay_id):
    return sorted(
        [r for r in db.build_slots.values() if r["work_bay_id"] == bay_id],
        key=db.sort_key,
    )


def certifications_of(order_id):
    return sorted(
        [r for r in db.weight_certifications.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def labels_of(order_id):
    return sorted(
        [r for r in db.compliance_labels.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def claims_of(order_id):
    return sorted(
        [r for r in db.warranty_claims.values() if r["upfit_order_id"] == order_id],
        key=db.sort_key,
    )


def governing_chassis_model(order):
    """PRD section 2.11.  When the order holds a chassis the governing model is
    that physical unit's model; while unbound it is the model named by the
    build configuration."""
    if order.get("chassis_id"):
        unit = db.chassis_units.get(order["chassis_id"])
        if unit is not None:
            model = db.chassis_models.get(unit["chassis_model_id"])
            if model is not None:
                return model
    config = db.build_configurations.get(order.get("build_configuration_id"))
    if config is None:
        return None
    return db.chassis_models.get(config["chassis_model_id"])
