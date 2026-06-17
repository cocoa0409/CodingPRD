"""Domain thresholds — numeric constants from the PRD calculations (§2, §3)."""

# Printability weighted-scoring constants (PRD §3.2).
PRINTABILITY = {
    "W_MANIFOLD": 40,
    "W_FITS": 30,
    "W_WALL": 20,
    "W_OVERHANG": 10,
    "PRINTABLE_MIN": 70,
    "FLAGGED_MIN": 50,
}

# Pricing / scheduling constants (PRD §3.3, §2.7, §3.1).
SECONDS_PER_LAYER = 7
DEFAULT_SHIFT_CAPACITY_MINUTES = 480
DEFAULT_COOLDOWN_BUFFER_MIN = 15

# Rush tier surcharge percentages (PRD §3.3).
RUSH_TIER = {
    "STANDARD": 0,
    "EXPEDITE": 30,
    "RUSH": 75,
}

# Canonical fixture material/machine vocabulary used across the suite.
TEST_DEFAULTS = {
    "MATERIAL_RATE_CENTS_PER_CM3": 35,
    "MACHINE_RATE_CENTS_PER_MIN": 12,
    "SETUP_FEE_CENTS": 2500,
    "DENSITY_G_PER_CM3": 1.10,
    "MIN_WALL_THICKNESS_MM": 0.80,
    "MAX_OVERHANG_DEG": 45,
    "BUILD_X_MM": 145,
    "BUILD_Y_MM": 145,
    "BUILD_Z_MM": 185,
    "BIG_DEPOSIT_CENTS": 5_000_000,
}

# File A canonical geometry (line A: layer_h 0.05, qty 3).
FILE_A = {
    "volume_cm3": 8.40,
    "bbox_x_mm": 50,
    "bbox_y_mm": 50,
    "bbox_z_mm": 60,
    "min_wall_mm": 1.0,
    "max_overhang_deg": 40,
    "is_manifold": True,
}

# File B canonical geometry (line B: layer_h 0.10, qty 1).
FILE_B = {
    "volume_cm3": 4.00,
    "bbox_x_mm": 20,
    "bbox_y_mm": 20,
    "bbox_z_mm": 20,
    "min_wall_mm": 1.0,
    "max_overhang_deg": 40,
    "is_manifold": True,
}
