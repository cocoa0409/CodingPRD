"""In-memory data store.

Every dict starts empty; nothing is seeded at startup. All entities are created
through declared endpoints (PRD §4). The implementation_generator skill is
explicit that seeding is forbidden.
"""
from __future__ import annotations

import threading
import uuid


class DB:
    def __init__(self) -> None:
        # Coarse global lock — these benchmarks are functional, not high-throughput.
        self.lock = threading.RLock()

        self.purchase_agreements: dict = {}
        self.escrow_accounts: dict = {}
        self.earnest_money_deposits: dict = {}
        self.title_searches: dict = {}
        self.title_insurance_policies: dict = {}
        self.ccr_reviews: dict = {}
        self.closing_disclosures: dict = {}
        self.wire_instructions: dict = {}
        self.disbursements: dict = {}
        self.exchange_accounts: dict = {}
        self.users: dict = {}


def new_id() -> str:
    return str(uuid.uuid4())


DB_INSTANCE = DB()
