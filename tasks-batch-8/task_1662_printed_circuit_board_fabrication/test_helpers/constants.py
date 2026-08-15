"""Domain thresholds — numeric constants named in the PRD (§2.3, §2.5, §3)."""

# Logical clock (PRD §2.5): startup default is exactly this instant.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Pagination (PRD §2.3)
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100

# Laminate shelf life (PRD §3.5): expiry_date is exactly 365 days after manufacture_date.
SHELF_LIFE_DAYS = 365

# Drill review gates (PRD §3.4)
MIN_HOLE_MILS = 6
ASPECT_RATIO_CEILING_1OZ = 8.0
ASPECT_RATIO_CEILING_2OZ = 6.0

# Coupon retest budget and fees (PRD §3.7, §3.9)
MAX_RETESTS = 2
RETEST_FEE_CENTS = 1500
IMPEDANCE_LINE_FEE_CENTS = 2500
MAX_SPREAD_OHMS = 6.0

# Pricing floor (PRD §3.3)
MIN_LOT_CHARGE_CENTS = 2000

# Array yield model (PRD §3.3)
DEFECT_DENSITY_PER_SQIN = 0.01
ARRAY_YIELD_FLOOR = 0.50

# Lab booking rules (PRD §3.7)
LAB_BOOKING_MAX_MINUTES = 120
LAB_BOOKING_BUFFER_MINUTES = 15

# Pareto (PRD §3.8)
PARETO_VITAL_THRESHOLD = 80.0

# Default geometry used across tests ("G1"): a 2000x3000-mil board (6 sqin)
# stepped 2x2 on a 5000x7000-mil panel (35 sqin) at quantity 100.
# Per PRD §3.3: yield = max(0.50, 1 - 0.01*6) = 0.94; good = floor(4*0.94) = 3;
# panels_required = ceil(100/3) = 34; utilization = round_half_up(100*4*6/35, 2) = 68.57.
G1_BOARD_X_MILS = 2000
G1_BOARD_Y_MILS = 3000
G1_ARRAY_X = 2
G1_ARRAY_Y = 2
G1_PANEL_WIDTH_MILS = 5000
G1_PANEL_HEIGHT_MILS = 7000
G1_QUANTITY_BOARDS = 100
G1_BOARDS_PER_PANEL = 4
G1_ARRAY_YIELD = 0.94
G1_GOOD_BOARDS_PER_PANEL = 3
G1_PANELS_REQUIRED = 34
G1_UTILIZATION_PCT = 68.57

DEFAULT_SHIP_DATE = "2026-08-10T00:00:00Z"
DEFAULT_MANUFACTURE_DATE = "2025-09-01T00:00:00Z"  # expiry 2026-09-01, safely past the default ship date

# Booking windows that cover the logical clock at each step of a measurement
# sequence while keeping the >= 15 minute per-station clearance (PRD §3.7).
WINDOW_AT_DEFAULT_CLOCK = ("2026-07-31T23:30:00Z", "2026-08-01T00:30:00Z")
WINDOW_AT_0100 = ("2026-08-01T00:45:00Z", "2026-08-01T01:45:00Z")
WINDOW_AT_0200 = ("2026-08-01T02:00:00Z", "2026-08-01T03:00:00Z")
WINDOW_AT_0300 = ("2026-08-01T03:15:00Z", "2026-08-01T04:15:00Z")
CLOCK_0100 = "2026-08-01T01:00:00Z"
CLOCK_0200 = "2026-08-01T02:00:00Z"
# 03:15, not 03:00: the window above starts at 03:15 (15-minute clearance from
# the 02:00-03:00 booking), and PRD §3.7 admits a measurement only when the
# clock falls at or after starts_at and strictly before ends_at.
CLOCK_0300 = "2026-08-01T03:15:00Z"
