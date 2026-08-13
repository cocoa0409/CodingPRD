"""In-memory data store. Empty on every fresh boot (no seeding, per skill)."""

from threading import RLock

# Entity stores keyed by id
programs = {}
requirement_groups = {}
honors_policies = {}
courses = {}
students = {}
enrollments = {}
student_programs = {}
degree_audits = {}
substitution_waivers = {}
graduation_applications = {}
diplomas = {}

# Logical clock: starts exactly at 2026-08-01T00:00:00Z (never wall-clock)
logical_clock_iso = "2026-08-01T00:00:00Z"

# Global write lock — single-threaded semantics for the recompute cascade.
lock = RLock()
