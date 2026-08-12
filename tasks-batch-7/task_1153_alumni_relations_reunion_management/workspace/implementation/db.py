"""In-memory data store. Empty on every boot; no seeding, no persistence."""

from datetime import datetime, timezone


# Entity tables, keyed by id
records = {}            # AlumniRecord
research_cases = {}     # LostAlumniResearchCase
events = {}             # ReunionEvent
committees = {}         # ReunionCommittee
memberships = {}        # CommitteeMembership
ticket_tiers = {}       # TicketTier
registrations = {}      # EventRegistration
groups = {}             # AffinityGroup
programs = {}           # ChapterProgram
preferences = {}        # CommunicationPreference
campaigns = {}          # GiftCampaign
pledges = {}            # GiftPledge
publications = {}       # MemorabiliaPublication

# Global suppression list: set of (alumni_id, channel)
suppression_list = set()


class LogicalClock:
    """Server-side logical clock. Starts at exactly 2026-05-01T00:00:00Z and
    only advances when POST /alumni/_clock/set_current_utc is invoked.
    Never falls back to wall-clock time."""

    _value = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

    @classmethod
    def now(cls):
        return cls._value

    @classmethod
    def set(cls, dt):
        cls._value = dt


def logical_now():
    return LogicalClock.now()
