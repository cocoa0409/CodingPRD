"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

DEFAULTS = {
    "FORESTER_LICENSE": "F-100",
    "FORESTER_NAME": "Francis Forester",
    "FORESTER_EMAIL": "f@x.com",
    "LANDOWNER_NAME": "Lara Landowner",
    "LANDOWNER_EMAIL": "l@x.com",
    "LANDOWNER_TAX_ID": "T-1",
    "BUYER_NAME": "Blue Mill",
    "BUYER_LICENSE": "B-100",
    "CONTRACTOR_NAME": "CutCo",
    "CONTRACTOR_LICENSE": "C-100",
    "TRACT_NAME": "Tract A",
    "TRACT_COUNTY": "Covington",
    "TRACT_ACRES": 100,
    "STAND_NAME": "Stand 1",
    "STAND_ACRES": 50,
    "STAND_SPECIES": "PINE",
    "CRUISE_DATE": "2026-03-01",
    "WINDOW_START": "2026-06-01",
    "WINDOW_END": "2026-10-01",
    "METHOD": "CLEARCUT",
    "BID_OPEN": "2026-05-10T00:00:00Z",
    "BID_CLOSE": "2026-05-20T00:00:00Z",
    "HARVEST_START": "2026-06-01",
    "HARVEST_END": "2026-10-01",
    "ADVERTISED_MIN_CENTS": 10_000_000,
    "MIN_RATE_CENTS": 40_000,
    "RATE_CENTS_PER_MBF": 45_000,
    "DEPOSIT_CENTS": 100_000,
    "LUMP_SUM_CENTS": 8_000_000,
    "SCALED_DATE": "2026-06-20",
    "SPECIES": "PINE",
    "DIAMETER_IN": 14,
    "LENGTH_FT": 16,
    "LOG_COUNT": 1,
    "INSPECTION_TYPE": "ACTIVE_HARVEST",
    "SCHEDULED_DATE": "2026-06-25",
    "SURVEY_DATE": "2028-04-01",
    "LIVE_SEEDLINGS": 900,
    "PLANTED_DATE": "2027-03-01",
    "SEEDLINGS_PLANTED": 1000,
    "ANNUAL_CREDITS": 1000,
    "BASELINE_CREDITS": 250,
    "PRICE_PER_TCO2E": 3000,
    "ESTIMATED_TIMBER_NET": 10_000_000,
    "ENROLLMENT_START": "2027-01-01",
    "PERIOD_START": "2026-06-01",
    "PERIOD_END": "2026-07-01",
}

# Canonical 6-plot PINE tally used by many fixtures: alternates 1165/1285 so
# the certified volume reconciles to 300125 with sampling_error 2.00.
PINE_PLOTS_6 = [
    {"plot_number": 1, "species": "PINE", "volume_bf": 1165},
    {"plot_number": 2, "species": "PINE", "volume_bf": 1285},
    {"plot_number": 3, "species": "PINE", "volume_bf": 1165},
    {"plot_number": 4, "species": "PINE", "volume_bf": 1285},
    {"plot_number": 5, "species": "PINE", "volume_bf": 1165},
    {"plot_number": 6, "species": "PINE", "volume_bf": 1285},
]

# Alternate 6-plot tally producing certified volume 339780 at sampling 2.92.
PINE_PLOTS_6_ALT = [
    {"plot_number": 1, "species": "PINE", "volume_bf": 1300},
    {"plot_number": 2, "species": "PINE", "volume_bf": 1500},
    {"plot_number": 3, "species": "PINE", "volume_bf": 1300},
    {"plot_number": 4, "species": "PINE", "volume_bf": 1500},
    {"plot_number": 5, "species": "PINE", "volume_bf": 1300},
    {"plot_number": 6, "species": "PINE", "volume_bf": 1500},
]

# 5-plot high-variance tally producing sampling_error 48.40.
PINE_PLOTS_5_HIGH_VAR = [
    {"plot_number": 1, "species": "PINE", "volume_bf": 100},
    {"plot_number": 2, "species": "PINE", "volume_bf": 2000},
    {"plot_number": 3, "species": "PINE", "volume_bf": 100},
    {"plot_number": 4, "species": "PINE", "volume_bf": 2000},
    {"plot_number": 5, "species": "PINE", "volume_bf": 100},
]

# 4-plot tally producing sampling_error 2.38 (below the 10.00 cap) but under
# the 5-plot minimum.
PINE_PLOTS_4 = [
    {"plot_number": 1, "species": "PINE", "volume_bf": 1000},
    {"plot_number": 2, "species": "PINE", "volume_bf": 1100},
    {"plot_number": 3, "species": "PINE", "volume_bf": 1000},
    {"plot_number": 4, "species": "PINE", "volume_bf": 1100},
]

PINE_PLOTS_1 = [
    {"plot_number": 1, "species": "PINE", "volume_bf": 1165},
]


# PRD §3.1: a forester's `license_no` is unique per forester. Tests that build
# two independent scenarios in one test (e.g. dual-variant calculations) register
# two foresters, so the default license must be unique per call to avoid a
# spurious "license_no already registered" 400 from the PRD-required uniqueness
# check. Explicit `license_no=...` overrides still win.
_FORESTER_LICENSE_COUNTER = itertools.count(1)


def create_forester_payload(**overrides) -> dict:
    payload = {
        "license_no": "%s-%d" % (DEFAULTS["FORESTER_LICENSE"],
                                 next(_FORESTER_LICENSE_COUNTER)),
        "full_name": DEFAULTS["FORESTER_NAME"],
        "email": DEFAULTS["FORESTER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_landowner_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["LANDOWNER_NAME"],
        "email": DEFAULTS["LANDOWNER_EMAIL"],
        "tax_id": DEFAULTS["LANDOWNER_TAX_ID"],
    }
    payload.update(overrides)
    return payload


def create_buyer_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["BUYER_NAME"],
        "license_no": DEFAULTS["BUYER_LICENSE"],
    }
    payload.update(overrides)
    return payload


def create_contractor_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["CONTRACTOR_NAME"],
        "license_no": DEFAULTS["CONTRACTOR_LICENSE"],
    }
    payload.update(overrides)
    return payload


def create_tract_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TRACT_NAME"],
        "county": DEFAULTS["TRACT_COUNTY"],
        "total_acres": DEFAULTS["TRACT_ACRES"],
    }
    payload.update(overrides)
    return payload


def create_stand_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["STAND_NAME"],
        "acres": DEFAULTS["STAND_ACRES"],
        "primary_species": DEFAULTS["STAND_SPECIES"],
    }
    payload.update(overrides)
    return payload


def create_cruise_payload(**overrides) -> dict:
    payload = {
        "cruise_date": DEFAULTS["CRUISE_DATE"],
        "plots": PINE_PLOTS_6,
    }
    payload.update(overrides)
    return payload


def create_prescription_payload(**overrides) -> dict:
    payload = {
        "silvicultural_method": DEFAULTS["METHOD"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    payload.update(overrides)
    return payload


def create_sale_payload(**overrides) -> dict:
    payload = {
        "sale_type": "PER_UNIT",
        "scaling_rule": "DOYLE",
        "advertised_minimum_cents": DEFAULTS["ADVERTISED_MIN_CENTS"],
        "species_minimum_rates": [
            {"species": "PINE", "min_rate_cents_per_mbf": DEFAULTS["MIN_RATE_CENTS"]}
        ],
        "bid_open_at": DEFAULTS["BID_OPEN"],
        "bid_close_at": DEFAULTS["BID_CLOSE"],
        "harvest_window_start": DEFAULTS["HARVEST_START"],
        "harvest_window_end": DEFAULTS["HARVEST_END"],
    }
    payload.update(overrides)
    return payload


def create_bid_payload(**overrides) -> dict:
    payload = {
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
        "species_rates": [
            {"species": "PINE", "rate_cents_per_mbf": DEFAULTS["RATE_CENTS_PER_MBF"]}
        ],
    }
    payload.update(overrides)
    return payload


def create_scale_ticket_payload(**overrides) -> dict:
    payload = {
        "scaled_date": DEFAULTS["SCALED_DATE"],
        "species": DEFAULTS["SPECIES"],
        "small_end_diameter_in": DEFAULTS["DIAMETER_IN"],
        "length_ft": DEFAULTS["LENGTH_FT"],
        "log_count": DEFAULTS["LOG_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_settlement_payload(**overrides) -> dict:
    payload = {
        "kind": "PER_UNIT_PERIOD",
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    # PRD §3.6: a LUMP_MILESTONE settlement "instead carries a `milestone`" — it
    # does not carry period dates. Drop the period fields so a milestone payload
    # matches the shape the workflow narrative declares.
    if payload.get("kind") == "LUMP_MILESTONE":
        payload.pop("period_start", None)
        payload.pop("period_end", None)
    return payload


def create_inspection_payload(**overrides) -> dict:
    payload = {
        "inspection_type": DEFAULTS["INSPECTION_TYPE"],
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
    }
    payload.update(overrides)
    return payload


def create_survey_payload(**overrides) -> dict:
    payload = {
        "survey_date": DEFAULTS["SURVEY_DATE"],
        "live_seedlings_count": DEFAULTS["LIVE_SEEDLINGS"],
    }
    payload.update(overrides)
    return payload


def create_carbon_valuation_payload(**overrides) -> dict:
    payload = {
        "annual_credits_tco2e": DEFAULTS["ANNUAL_CREDITS"],
        "baseline_credits_tco2e": DEFAULTS["BASELINE_CREDITS"],
        "price_cents_per_tco2e": DEFAULTS["PRICE_PER_TCO2E"],
        "estimated_timber_net_cents": DEFAULTS["ESTIMATED_TIMBER_NET"],
        "enrollment_start": DEFAULTS["ENROLLMENT_START"],
    }
    payload.update(overrides)
    return payload


def create_record_planting_payload(**overrides) -> dict:
    payload = {
        "planted_date": DEFAULTS["PLANTED_DATE"],
        "seedlings_planted": DEFAULTS["SEEDLINGS_PLANTED"],
    }
    payload.update(overrides)
    return payload
