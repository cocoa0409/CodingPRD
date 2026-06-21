"""Domain constants (scaffold §1.2/§1.3 constants, PRD §3)."""

MIN_START_BATTERY_PCT = 20          # trip start/end legal-park threshold (PRD §3.3, §3.5)
GRACE_SECONDS = 120                 # trip cancel grace window (PRD §3.5)
AUTO_SWAP_WINDOW_SECONDS = 3600     # auto SWAP task window length (PRD §3.5)
TASK_BUFFER_SECONDS = 600           # buffered window-overlap padding (PRD §3.7)
PROJECTED_TRIP_MINUTES = 15         # provisional fare projection (PRD §3.3)
SECONDS_PER_MINUTE = 60
INCOME_CEILING_PER_PERSON_CENTS = 3000000   # low-income approval ceiling (PRD §3.2)
BASE_PARKING_FINE_CENTS = 2500      # base parking fine (PRD §3.5)
LOW_INCOME_FINE_DISCOUNT_PCT = 0.40  # low-income fine reduction (PRD §3.5)
