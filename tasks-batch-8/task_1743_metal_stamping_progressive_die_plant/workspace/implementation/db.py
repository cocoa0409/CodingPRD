"""In-memory data store. Starts empty on every boot — no seeding."""

# Entity stores keyed by id
customers = {}
parts = {}
dies = {}
presses = {}
part_die_assignments = {}
steel_coils = {}
strip_layouts = {}
production_orders = {}
die_change_events = {}
production_runs = {}
reject_events = {}
outside_processing_orders = {}
ppap_submissions = {}
layered_audits = {}
index_publications = {}
price_adjustments = {}
