"""In-memory data store keyed by entity id (UUID, no prefix)."""
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        # parties and catalog
        self.design_categories = {}      # id -> DesignCategory
        self.design_categories_by_code = {}  # code -> id
        self.clients = {}                # id -> Client
        self.designers = {}              # id -> Designer
        self.designers_by_display_name = {}  # display_name -> id
        self.reviewers = {}              # id -> ReviewerPool record (id == reviewer_id)
        # project graph
        self.projects = {}               # id -> Project
        self.prize_tiers = {}            # id -> PrizeTier
        self.review_stages = {}          # id -> ReviewStage
        self.submissions = {}            # id -> Submission
        self.review_assignments = {}     # id -> ReviewAssignment
        # disputes / copyright / payments
        self.disputes = {}               # id -> Dispute
        self.copyright_transfers = {}    # id -> CopyrightTransfer
        self.prize_payments = {}         # id -> PrizePayment
        # audit
        self.audit_events = {}           # id -> AuditEvent
        # idempotency: idempotency_key -> prize_payment_id (active, PAYING/PAID)
        self.payment_idempotency_index = {}


db = DB()
