"""In-memory data store with UUID generation."""

import uuid


def new_id():
    return str(uuid.uuid4())


DB = {
    "stations": {},                # id -> Station
    "charging_slots": {},          # id -> ChargingSlot
    "battery_models": {},          # id -> BatteryModel
    "vehicle_models": {},          # id -> VehicleModel
    "compatibility_rules": {},     # id -> CompatibilityRule
    "batteries": {},               # id -> Battery
    "vehicles": {},                # id -> Vehicle
    "members": {},                 # id -> Member
    "reservations": {},            # id -> Reservation
    "swap_events": {},             # id -> SwapEvent
    "billing_records": {},         # id -> BillingRecord
    "dispatch_orders": {},         # id -> DispatchOrder
    "soh_assessments": {},         # id -> SOHAssessment
    "audit_logs": {},              # id -> AuditLog
}


def reset():
    for k in DB:
        DB[k] = {}
