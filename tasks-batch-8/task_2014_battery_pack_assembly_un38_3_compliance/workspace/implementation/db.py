"""In-memory data store. Everything lives in module-level dicts keyed by id.
No disk persistence of any kind; every process boot starts empty. No seeding:
all entities are constructed exclusively through the declared API surface."""

import itertools
import uuid

# entity collection -> {id: row dict}
programs = {}            # IntegrationProgram
cell_lots = {}           # CellLot
inspections = {}         # CellInspectionRecord (immutable event)
boms = {}                # PackBOM
packs = {}               # BatteryPack
weld_records = {}        # WeldingParameterRecord (immutable event)
firmwares = {}           # BMSFirmware
approvals = {}           # FirmwareApproval (immutable event)
flash_records = {}       # BMSFlashRecord (immutable event)
dossiers = {}            # SafetyTestDossier
locations = {}           # StorageLocation
placements = {}          # StoragePlacement
shipments = {}           # TransportShipment
links = {}               # ShipmentPackLink (immutable event)
rmas = {}                # ReturnAuthorization
recalls = {}             # RecallCampaign

# monotonic insertion sequence for stable created_at ordering
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())
