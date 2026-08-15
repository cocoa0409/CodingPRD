"""In-memory store. Every dict is keyed by entity id and starts empty at boot.
No seeding, no persistence — per-test-server isolation gives a fresh process.
"""

volunteers = {}
certifications = {}
seasons = {}
beds = {}
crop_plans = {}
slots = {}
signups = {}
bookings = {}
keys = {}
tools = {}
checkouts = {}
harvests = {}
recipients = {}
allocations = {}
irrigations = {}
