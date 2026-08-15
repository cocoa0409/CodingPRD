"""In-memory data store.

The store starts completely empty on every boot (per-test-server isolation).
No seeding of any kind happens here — every entity a test needs is built
through the declared API surface.
"""


class Store:
    def __init__(self):
        self.customers = {}          # CustomerAccount
        self.formulas = {}           # Formula
        self.supplies = {}           # IngredientSupply
        self.pilot_cells = {}        # PilotCell
        self.trials = {}             # ScaleUpTrial
        self.letters = {}            # ProcessAuthorityLetter
        self.kettle_lines = {}       # KettleLine
        self.components = {}         # PackagingComponent
        self.runs = {}               # ProductionRun
        self.holds = {}              # QualityHold
        self.labels = {}             # LabelApproval
        self.seq = 0                 # monotonic creation sequence (insertion order)

    def next_seq(self):
        self.seq += 1
        return self.seq


STORE = Store()
