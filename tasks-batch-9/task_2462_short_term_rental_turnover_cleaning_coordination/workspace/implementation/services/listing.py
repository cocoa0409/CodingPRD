"""Collection ordering (PRD 2.3).  `_seq` is only ever a final stable tiebreak."""


def sort_default(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def sort_supply_lines(rows):
    return sorted(rows, key=lambda r: (r["sku"], r["_seq"]))


def sort_stock_movements(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["sequence_no"], r["_seq"]))


def sort_bookings(rows):
    return sorted(rows, key=lambda r: (r["checkin_at"], r["created_at"], r["_seq"]))


def sort_turnovers(rows):
    return sorted(rows, key=lambda r: (r["window_start_at"], r["created_at"], r["_seq"]))


def sort_checklist_tasks(rows):
    return sorted(rows, key=lambda r: (r["sequence_no"], r["_seq"]))


def sort_assignments(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["sequence_no"], r["_seq"]))
