"""Error catalogue for the Themed Attraction Development API.

Every error_id / HTTP status pair below is taken verbatim from PRD.md section 5
(and cross-checked against SCAFFOLD.yaml `errors`).
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
    "ERR_UNAUTHORIZED": "The caller's role is not permitted to perform this operation.",
    "ERR_INVALID_REQUEST": "The request body or query parameters do not conform to the endpoint's input schema.",
    "ERR_PROJECT_NOT_FOUND": "The referenced attraction project does not exist.",
    "ERR_RIDE_SYSTEM_NOT_FOUND": "The referenced ride system does not exist.",
    "ERR_QUEUE_SEGMENT_NOT_FOUND": "The referenced queue segment does not exist.",
    "ERR_SCENE_NOT_FOUND": "The referenced show scene does not exist.",
    "ERR_CUE_NOT_FOUND": "The referenced effect cue does not exist.",
    "ERR_PACKAGE_NOT_FOUND": "The referenced design package does not exist.",
    "ERR_REVIEW_NOT_FOUND": "The referenced safety review does not exist.",
    "ERR_FINDING_NOT_FOUND": "The referenced safety finding does not exist.",
    "ERR_VE_ITEM_NOT_FOUND": "The referenced value-engineering item does not exist.",
    "ERR_REHEARSAL_RUN_NOT_FOUND": "The referenced rehearsal run does not exist.",
    "ERR_MAINTENANCE_ITEM_NOT_FOUND": "The referenced maintenance item does not exist.",
    "ERR_LEDGER_ENTRY_NOT_FOUND": "The referenced budget ledger entry does not exist.",
    "ERR_STALE_PROJECT_VERSION": "expected_project_version does not match the current project version.",
    "ERR_STALE_PACKAGE_VERSION": "expected_package_version does not match the current design package version.",
    "ERR_STALE_RIDE_SYSTEM_VERSION": "expected_ride_system_version does not match the current ride system version.",
    "ERR_RIDE_SYSTEM_STATE_INVALID": "The ride system is not in the state this action requires.",
    "ERR_QUEUE_SEGMENT_STATE_INVALID": "The queue segment is not in the state this action requires.",
    "ERR_SCENE_STATE_INVALID": "The show scene is not in the state this action requires.",
    "ERR_CUE_STATE_INVALID": "The effect cue or its owning scene is not in the state this action requires.",
    "ERR_PACKAGE_STATE_INVALID": "The design package is not in the state this action requires.",
    "ERR_REVIEW_STATE_INVALID": "The safety review is not in the state this action requires.",
    "ERR_FINDING_STATE_INVALID": "The safety finding is not in the state this action requires.",
    "ERR_VE_ITEM_STATE_INVALID": "The value-engineering item is not in the state this action requires.",
    "ERR_REHEARSAL_STATE_INVALID": "The rehearsal run is not in the state this action requires.",
    "ERR_MAINTENANCE_STATE_INVALID": "The maintenance item is not in the state this action requires.",
    "ERR_PROJECT_FROZEN": "The programme is FROZEN and refuses this write.",
    "ERR_POSTURE_RESTRICTED": "The programme is RESTRICTED and refuses scope-increasing writes.",
    "ERR_PHASE_SEQUENCE_INVALID": "to_phase is not the immediate successor of the current design phase.",
    "ERR_PROJECT_PHASE_INVALID": "The programme's design phase does not permit this operation.",
    "ERR_SEGREGATION_OF_DUTIES": "The approving user may not be the submitting user.",
    "ERR_CRITICAL_FINDING_NOT_WAIVABLE": "A CRITICAL safety finding may never be waived.",
    "ERR_OPEN_FINDINGS_PRESENT": "The safety review still has open findings.",
    "ERR_SAFETY_REVIEW_NOT_CLEARED": "No cleared safety review exists for an approved package, or a critical finding is open.",
    "ERR_PINNED_REFERENCE_STALE": "The pinned ride system version is no longer current.",
    "ERR_RIDE_SYSTEM_PROJECT_MISMATCH": "The named ride system belongs to a different project.",
    "ERR_BALLOT_PARTY_ROLE_MISMATCH": "The ballot party_role must equal the caller's X-User-Role.",
    "ERR_REHEARSAL_RUN_PROJECT_MISMATCH": "The cited rehearsal run belongs to a different project.",
    "ERR_REHEARSAL_NOT_PASSED": "The cited rehearsal run is not COMPLETED with result PASS.",
    "ERR_REHEARSAL_WINDOW_CONFLICT": "The requested rehearsal window conflicts with an existing run.",
    "ERR_SOFT_OPEN_ALREADY_SCHEDULED": "A soft-open run already exists for this programme on that UTC date.",
    "ERR_REHEARSAL_WINDOW_NOT_ELAPSED": "The rehearsal window has not elapsed yet.",
    "ERR_CUE_CHANNEL_CONFLICT": "The cue collides with another cue on the same scene and discipline channel.",
    "ERR_PROJECT_CODE_DUPLICATE": "project_code already exists.",
    "ERR_SCENE_SEQUENCE_DUPLICATE": "sequence_index is already used by another scene of this programme.",
    "ERR_SCENE_ORDER_CYCLE": "The requested predecessor would close a cycle in the running order.",
    "ERR_CUES_NOT_VERIFIED": "The scene must own at least one cue and every cue must be VERIFIED.",
    "ERR_SCENE_NOT_READY": "Every scene of the programme must be VALIDATED.",
    "ERR_SHOW_QUALITY_BELOW_MINIMUM": "The programme show quality score is below the minimum.",
    "ERR_QUEUE_POSITION_DUPLICATE": "position_index is already used by a live segment of this programme.",
    "ERR_QUEUE_WIDTH_BELOW_MINIMUM": "width_meters is below the routing-class minimum.",
    "ERR_ACCESSIBLE_ROUTE_MISSING": "No accepted ACCESSIBLE queue segment exists.",
    "ERR_ACCESSIBLE_SHARE_INSUFFICIENT": "The accessible share of queue capacity is insufficient.",
    "ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED": "virtual_queue_share_pct exceeds the business cap.",
    "ERR_RIDE_SYSTEM_ALREADY_ENGINEERED": "Another ride system of this programme is already ENGINEERED or COMMISSIONED.",
    "ERR_CAPACITY_TARGET_NOT_MET": "The operational hourly capacity is below the required hourly capacity.",
    "ERR_VE_ADOPTION_BREAKS_CAPACITY": "Adopting the item would drop the selected system below the required hourly capacity.",
    "ERR_SCOPE_IMPACT_DELTA_MISMATCH": "scope_impact_delta_cents must equal implementation_cost_cents minus gross_saving_cents.",
    "ERR_BALLOT_ALREADY_CAST": "A ballot for this party_role has already been cast on this item.",
    "ERR_VETO_NOT_PERMITTED": "The designer party may not cast a VETO.",
    "ERR_MAINTENANCE_PART_DUPLICATE": "part_number already exists for this programme.",
    "ERR_SPARE_STOCK_INSUFFICIENT": "stocked_qty is below recommended_stock_qty.",
    "ERR_MAINTENANCE_NOT_HANDED_OVER": "Every maintenance item of the programme must be HANDED_OVER.",
    "ERR_SOFT_OPEN_NOT_VALIDATED": "soft_open_validated must be true.",
    "ERR_LEDGER_KIND_NOT_WRITABLE": "Only CHANGE_ORDER entries may be written directly by a client.",
    "ERR_LEDGER_ENTRY_ALREADY_REVERSED": "The ledger entry has already been reversed or is itself a reversal.",
    "ERR_BUDGET_CEILING_EXCEEDED": "The requested amount would push committed cost above the budget ceiling.",
    "ERR_PHASE_PRECONDITION_UNMET": "The content preconditions of the requested design phase are not met.",
}


def invalid(message=None):
    return ApiError("ERR_INVALID_REQUEST", 400, message)
