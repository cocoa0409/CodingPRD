"""In-memory data store. Starts empty on every boot -- no seeding."""
import threading

lock = threading.RLock()

licensees = {}
agreements = {}
milestones = {}
sublicense_grants = {}
reports = {}
audits = {}
findings = {}
disputes = {}
distribution_runs = {}

# Logical clock state (ISO 8601 string). Default before any clock-set call.
current_utc = "2026-08-01T00:00:00Z"
