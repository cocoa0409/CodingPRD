"""Error catalogue (SCAFFOLD.yaml §1.6 / PRD §5)."""

ERROR_CATALOG = {
    "ERR_MISSING_ROLE": (401, "X-Role header is required"),
    "ERR_UNAUTHORIZED": (403, "role is not permitted to perform this operation"),
    "ERR_MISSING_USER": (401, "X-User-ID header is required for this operation"),
    "ERR_INVALID_REQUEST": (400, "required field missing or wrongly typed"),
    "ERR_INVALID_ENUM": (400, "field value is outside the permitted set"),
    "ERR_VALUE_OUT_OF_RANGE": (400, "numeric field is outside its permitted range"),
    "ERR_INVALID_WINDOW": (400, "window_end must be after window_start"),
    "ERR_PACKAGE_NOT_FOUND": (404, "facade package does not exist"),
    "ERR_SUBMITTAL_NOT_FOUND": (404, "shop drawing submittal does not exist"),
    "ERR_GLASS_ORDER_NOT_FOUND": (404, "glass order does not exist"),
    "ERR_ZONE_NOT_FOUND": (404, "installation zone does not exist"),
    "ERR_LOT_NOT_FOUND": (404, "panel lot or fabrication release does not exist"),
    "ERR_SURVEY_NOT_FOUND": (404, "anchor embed survey does not exist"),
    "ERR_TEST_NOT_FOUND": (404, "mockup test or field test does not exist"),
    "ERR_DEFECT_NOT_FOUND": (404, "defect item does not exist"),
    "ERR_HOIST_NOT_FOUND": (404, "hoist rig or reservation does not exist"),
    "ERR_RESOURCE_NOT_FOUND": (
        404,
        "referenced test lab, crew day log or breakage draw does not exist",
    ),
    "ERR_STALE_PACKAGE_VERSION": (
        412,
        "expected_package_version does not match the current facade package version",
    ),
    "ERR_STALE_GLASS_ORDER_VERSION": (
        412,
        "expected_glass_order_version does not match the current glass order version",
    ),
    "ERR_INVALID_STATE": (
        409,
        "the entity's current state has no transition for this trigger",
    ),
    "ERR_TERMINAL_STATE": (
        409,
        "the entity is in a terminal state and accepts no further transitions",
    ),
    "ERR_ZONE_SEQUENCE_VIOLATION": (
        409,
        "the zone is not at the install_status this operation requires",
    ),
    "ERR_DISPUTE_REF_REQUIRED": (
        409,
        "an escalated submittal can only be resubmitted with a dispute_resolution_ref",
    ),
    "ERR_COATING_REVISION_AFTER_RECEIPT": (
        409,
        "the coating specification cannot be revised once the glass has been received",
    ),
    "ERR_CREW_DAY_DUPLICATE": (
        409,
        "a posted crew day already exists for this zone and work_date",
    ),
    "ERR_HOIST_WINDOW_CONFLICT": (
        409,
        "the requested rig window conflicts with an existing reservation once the "
        "changeover buffer is applied",
    ),
    "ERR_LAB_CAPACITY_EXCEEDED": (
        409,
        "the lab has no free chamber for the requested window",
    ),
    "ERR_SEAL_REQUIRED": (
        422,
        "a delegated-design or structural-calculation submittal must be sealed before review",
    ),
    "ERR_SEAL_INVALID": (
        422,
        "the seal is missing a license number or the revision is already sealed",
    ),
    "ERR_SEALER_CANNOT_REVIEW": (422, "the engineer who sealed the set cannot review it"),
    "ERR_INSPECTOR_CONFLICT": (
        422,
        "the inspector who raised the item cannot re-inspect it",
    ),
    "ERR_SUBMITTAL_NOT_APPROVED": (
        422,
        "fabrication requires an approved or approved-as-noted submittal",
    ),
    "ERR_ENGINEERING_POSTURE_FROZEN": (
        422,
        "the package's engineering posture is FROZEN",
    ),
    "ERR_MOCKUP_NOT_QUALIFIED": (
        422,
        "no performance mockup has passed for this package",
    ),
    "ERR_EMBED_SURVEY_NOT_ACCEPTED": (
        422,
        "the zone has no poured, accepted embed survey",
    ),
    "ERR_POUR_BEFORE_ACCEPTANCE": (
        422,
        "the pour cannot be confirmed before the embeds are accepted",
    ),
    "ERR_PANEL_LOTS_NOT_SHIPPED": (
        422,
        "every panel lot of the zone must be shipped before panels are hung",
    ),
    "ERR_HOIST_WINDOW_INVALID": (
        422,
        "the referenced hoist reservation is not usable now",
    ),
    "ERR_NO_FIELD_TEST_EVIDENCE": (
        422,
        "weather-tightness certification requires a passed water test and a passed air test",
    ),
    "ERR_OPEN_CRITICAL_DEFECT": (422, "a critical defect is still open in scope"),
    "ERR_THERMAL_MOVEMENT_EXCEEDED": (
        422,
        "computed thermal movement exceeds the detailed joint width",
    ),
    "ERR_DEFLECTION_LIMIT_UNSET": (
        422,
        "the deflection limit is unknown until the system type is decided",
    ),
    "ERR_WAIVER_NOT_PERMITTED": (422, "critical defects cannot be waived"),
    "ERR_GLASS_BALANCE_INSUFFICIENT": (
        422,
        "the glass order has too few unallocated lites for this release",
    ),
    "ERR_BREAKAGE_STOCK_EXHAUSTED": (
        422,
        "the requested draw exceeds available breakage stock",
    ),
    "ERR_DRAW_QUANTITY_INVALID": (
        422,
        "the requested draw exceeds the glass content of the lot being repaired",
    ),
    "ERR_GLASS_RISK_THRESHOLD_EXCEEDED": (
        422,
        "the glass order's procurement risk score is at or above the release threshold",
    ),
    "ERR_BILLING_EXCEEDS_CONTRACT": (
        422,
        "certifying this zone would bill past the contract value",
    ),
    "ERR_ZONES_NOT_WEATHER_TIGHT": (
        422,
        "every zone must be weather-tight before close-out",
    ),
    "ERR_PUNCH_LIST_OPEN": (
        422,
        "open punch items or open submittal notes block close-out",
    ),
}


class ApiError(Exception):
    """Domain error carrying the scaffold error_id, HTTP status and message."""

    def __init__(self, error_id, message=None):
        status, default_message = ERROR_CATALOG.get(error_id, (400, "request failed"))
        super().__init__(message or default_message)
        self.error_id = error_id
        self.http_status = status
        self.message = message or default_message
