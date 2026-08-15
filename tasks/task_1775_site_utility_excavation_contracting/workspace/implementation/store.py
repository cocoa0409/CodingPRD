"""In-memory data store. Empty at boot; never seeded."""

projects = {}             # id -> Project dict
utility_owners = {}       # id -> UtilityOwner dict
locate_tickets = {}       # id -> LocateTicket
pothole_verifications = {}
trench_safety_plans = {}
pipe_segments = {}
installation_inspections = {}
shutdown_windows = {}
discharge_permits = {}
discharge_readings = {}
compaction_tests = {}
as_built_packages = {}
unforeseen_conditions = {}
change_orders = {}
audit_events = {}         # id -> AuditEvent


ENTITY_STORES = {
    "Project": projects,
    "UtilityOwner": utility_owners,
    "LocateTicket": locate_tickets,
    "PotholeVerification": pothole_verifications,
    "TrenchSafetyPlan": trench_safety_plans,
    "PipeSegment": pipe_segments,
    "InstallationInspection": installation_inspections,
    "ShutdownWindow": shutdown_windows,
    "DischargePermit": discharge_permits,
    "DischargeReading": discharge_readings,
    "CompactionTest": compaction_tests,
    "AsBuiltPackage": as_built_packages,
    "UnforeseenCondition": unforeseen_conditions,
    "ChangeOrder": change_orders,
}
