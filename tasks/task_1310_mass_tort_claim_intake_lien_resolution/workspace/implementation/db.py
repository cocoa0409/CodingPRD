"""In-memory data store. All state lives in module-level dicts.

The store starts completely empty on every boot. No seeding is performed.
"""

# Primary stores keyed by UUID id
programs = {}          # id -> SettlementProgram dict
claimants = {}         # id -> Claimant dict
claims = {}            # id -> Claim dict
tier_matrices = {}     # id -> TierMatrix dict
medical_records = {}   # id -> MedicalRecord dict
liens = {}             # id -> Lien dict
appeals = {}           # id -> Appeal dict
disbursements = {}     # id -> Disbursement dict
closing_statements = {} # id -> ClosingStatement dict

# Counter for claim_number minting (CLM-####)
_claim_number_counter = [0]


def next_claim_number():
    _claim_number_counter[0] += 1
    return "CLM-%04d" % _claim_number_counter[0]


def reset():
    """Clear all stores (used for testing; not called at startup)."""
    programs.clear()
    claimants.clear()
    claims.clear()
    tier_matrices.clear()
    medical_records.clear()
    liens.clear()
    appeals.clear()
    disbursements.clear()
    closing_statements.clear()
    _claim_number_counter[0] = 0
