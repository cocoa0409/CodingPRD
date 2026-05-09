"""In-memory data store."""
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class DB:
    def __init__(self):
        self.rights_holders = {}        # id -> RightsHolder
        self.works = {}                 # id -> Work
        self.licenses = {}              # id -> License
        self.negotiation_rounds = {}    # id -> NegotiationRound
        self.contracts = {}             # id -> Contract
        self.signatures = {}            # id -> Signature
        self.royalty_statements = {}    # id -> RoyaltyStatement
        self.infringement_cases = {}    # id -> InfringementCase
        self.rights_chain_events = {}   # id -> RightsChainEvent
        self.external_events = {}       # id -> ExternalEvent
        self.audit_logs = {}            # id -> AuditLog
        # external event idempotency: (source, external_event_id) -> event id
        self.external_event_index = {}


db = DB()
