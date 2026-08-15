"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts EMPTY on every boot — no seeding, no preload.
"""
import itertools
import threading


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.engagements = {}          # id -> AuditEngagement dict
        self.locations = {}            # id -> Location dict
        self.pbc_requests = {}         # id -> PBCRequest dict
        self.evidence_uploads = {}     # id -> EvidenceUpload dict
        self.queries = {}              # id -> AuditorQuery dict
        self.sampling_requests = {}    # id -> SamplingRequest dict
        self.fieldwork_visits = {}     # id -> FieldworkVisit dict
        self.adjustments = {}          # id -> AuditAdjustment dict
        self.representation_letters = {}  # id -> RepresentationLetter dict
        self.fee_change_requests = {}  # id -> FeeChangeRequest dict
        self._request_counter = itertools.count(1)


db = Store()
