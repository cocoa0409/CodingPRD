"""In-memory data store.

All state lives in module-level dicts keyed by id. The store starts empty on
every boot — no seeding, no preloading, no persistence of any kind.
"""

# Entity collections, keyed by entity id.
projects = {}
batches = {}
assets = {}
watermark_profiles = {}
dailies_packages = {}
edit_bays = {}
bookings = {}
turnovers = {}
change_lists = {}
review_rounds = {}
review_notes = {}
deliverables = {}
qc_reports = {}
archive_jobs = {}
vendors = {}
vendor_bids = {}
