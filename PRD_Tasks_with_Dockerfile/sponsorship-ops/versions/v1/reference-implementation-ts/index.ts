import express, { Request, Response, NextFunction } from "express";
import crypto from "node:crypto";

type EventPosture = "DRAFT" | "OPEN" | "LOCKDOWN" | "ARCHIVED";
type PackageStatus = "ACTIVE" | "RETIRED";
type SponsorStatus = "PROSPECT" | "VETTED" | "WATCHLIST" | "BLOCKED";
type ApplicationStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED" | "WITHDRAWN" | "EXPIRED";
type HoldStatus = "HELD" | "WAITLISTED";
type CommitmentStatus = "PENDING_COUNTERSIGN" | "ACTIVE" | "SUSPENDED" | "RESCINDED";
type ClaimStatus = "PROPOSED" | "FINALIZED" | "VOIDED";
type BenefitKind = "LEAD_SCANS" | "STAGE_MINUTES" | "SPOTLIGHT";

type ErrorCode =
  | "ERR_BAD_REQUEST"
  | "ERR_NOT_FOUND"
  | "ERR_PRECONDITION_REQUIRED"
  | "ERR_VERSION_CONFLICT"
  | "ERR_EVENT_NOT_OPEN"
  | "ERR_EVENT_LOCKDOWN"
  | "ERR_INVALID_STATE"
  | "ERR_PACKAGE_RETIRED"
  | "ERR_DUPLICATE_APPLICATION"
  | "ERR_DUPLICATE_COMMITMENT"
  | "ERR_NO_ACTIVE_HOLD"
  | "ERR_SPONSOR_BLOCKED"
  | "ERR_COMMITMENT_NOT_ACTIVE"
  | "ERR_BENEFIT_NOT_INCLUDED"
  | "ERR_INSUFFICIENT_BENEFIT"
  | "ERR_DUPLICATE_CLAIM"
  | "ERR_SPOTLIGHT_FULL"
  | "ERR_SPOTLIGHT_IN_USE"
  | "ERR_HAS_FINALIZED_CLAIMS";

type IncludedBenefit = { benefit_kind: BenefitKind; quantity: number };

type EventRec = {
  id: string;
  name: string;
  spotlight_slot_count: number;
  posture: EventPosture;
  ops_run_index: number;
  version: number;

  packages: Map<string, PackageRec>;
  sponsors: Map<string, SponsorRec>;
  applications: Map<string, ApplicationRec>;
  commitments: Map<string, CommitmentRec>;
  claims: Map<string, ClaimRec>;
};

type PackageRec = {
  id: string;
  label: string;
  price_cents: number;
  slot_count: number;
  included_benefits: IncludedBenefit[];
  status: PackageStatus;
  version: number;
  submit_seq_counter: number;
};

type SponsorRec = {
  id: string;
  display_name: string;
  legal_name?: string;
  primary_contact_email: string;
  status: SponsorStatus;
  version: number;
};

type ApplicationRec = {
  id: string;
  sponsor_id: string;
  package_id: string;
  status: ApplicationStatus;
  version: number;

  note?: string;

  submit_seq: number | null;
  hold_status: HoldStatus | null;
  hold_expires_on_ops: number | null;
  commitment_id: string | null;
};

type CommitmentRec = {
  id: string;
  sponsor_id: string;
  package_id: string;
  application_id: string;
  status: CommitmentStatus;
  version: number;

  activation_deadline_on_ops: number | null;

  claim_ids: string[];
};

type ClaimRec = {
  id: string;
  commitment_id: string;
  benefit_kind: BenefitKind;
  quantity: number;
  status: ClaimStatus;
  version: number;
};

const HOLD_TTL_OPS = 2;
const ACTIVATION_TTL_OPS = 3;

const db: { events: Map<string, EventRec> } = { events: new Map() };

class ApiErr extends Error {
  status: number;
  code: ErrorCode;
  constructor(status: number, code: ErrorCode, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function err(status: number, code: ErrorCode, message: string): never {
  throw new ApiErr(status, code, message);
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isNonEmptyString(v: unknown): v is string {
  return typeof v === "string" && v.trim().length > 0;
}

function isInt(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v) && Number.isInteger(v);
}

function isNonNegativeInt(v: unknown): v is number {
  return isInt(v) && v >= 0;
}

function isPositiveInt(v: unknown): v is number {
  return isInt(v) && v > 0;
}

function normalizeIfMatch(h: unknown): number {
  if (!isNonEmptyString(h)) err(400, "ERR_BAD_REQUEST", "Invalid If-Match header.");
  const raw = h.trim();
  const stripped = raw.startsWith('"') && raw.endsWith('"') ? raw.slice(1, -1) : raw;
  const n = Number(stripped);
  if (!Number.isInteger(n) || !Number.isFinite(n)) err(400, "ERR_BAD_REQUEST", "Invalid If-Match header.");
  return n;
}

function requireIfMatch(req: Request): number {
  const h = req.header("If-Match");
  if (!h) err(428, "ERR_PRECONDITION_REQUIRED", "Missing required If-Match header.");
  return normalizeIfMatch(h);
}

function genId(prefix: string): string {
  return `${prefix}_${crypto.randomUUID()}`;
}

function sendSuccess(res: Response, status: number, data: unknown) {
  res.status(status).json({ response_type: "success", data });
}

function sendError(res: Response, status: number, code: ErrorCode, message: string) {
  res.status(status).json({ response_type: "error", message, data: { error_code: code } });
}

function getEvent(event_id: string): EventRec {
  const ev = db.events.get(event_id);
  if (!ev) err(404, "ERR_NOT_FOUND", "Event not found.");
  return ev;
}

function getPackage(ev: EventRec, package_id: string): PackageRec {
  const p = ev.packages.get(package_id);
  if (!p) err(404, "ERR_NOT_FOUND", "Package not found.");
  return p;
}

function getSponsor(ev: EventRec, sponsor_id: string): SponsorRec {
  const s = ev.sponsors.get(sponsor_id);
  if (!s) err(404, "ERR_NOT_FOUND", "Sponsor not found.");
  return s;
}

function getApplication(ev: EventRec, application_id: string): ApplicationRec {
  const a = ev.applications.get(application_id);
  if (!a) err(404, "ERR_NOT_FOUND", "Application not found.");
  return a;
}

function getCommitment(ev: EventRec, commitment_id: string): CommitmentRec {
  const c = ev.commitments.get(commitment_id);
  if (!c) err(404, "ERR_NOT_FOUND", "Commitment not found.");
  return c;
}

function getClaim(ev: EventRec, claim_id: string): ClaimRec {
  const c = ev.claims.get(claim_id);
  if (!c) err(404, "ERR_NOT_FOUND", "Claim not found.");
  return c;
}

function assertEventNotLockedForCreation(ev: EventRec) {
  if (ev.posture === "LOCKDOWN" || ev.posture === "ARCHIVED") {
    err(409, "ERR_EVENT_LOCKDOWN", "Event is in lockdown/archived posture.");
  }
}

function assertEventOpenForProgress(ev: EventRec) {
  if (ev.posture === "LOCKDOWN" || ev.posture === "ARCHIVED") {
    err(409, "ERR_EVENT_LOCKDOWN", "Event is in lockdown/archived posture.");
  }
  if (ev.posture !== "OPEN") {
    err(409, "ERR_EVENT_NOT_OPEN", "Event is not open for sponsor-facing progress.");
  }
}

function assertSponsorNotBlocked(s: SponsorRec) {
  if (s.status === "BLOCKED") err(409, "ERR_SPONSOR_BLOCKED", "Sponsor is blocked.");
}

function benefitKinds(): BenefitKind[] {
  return ["LEAD_SCANS", "STAGE_MINUTES", "SPOTLIGHT"];
}

function isBenefitKind(v: unknown): v is BenefitKind {
  return typeof v === "string" && (benefitKinds() as string[]).includes(v);
}

function computeEventSpotlightUsed(ev: EventRec): number {
  let used = 0;
  for (const claim of ev.claims.values()) {
    if (claim.benefit_kind === "SPOTLIGHT" && claim.status === "FINALIZED") used += 1;
  }
  return used;
}

function computeEventSpotlightRemaining(ev: EventRec): number {
  const used = computeEventSpotlightUsed(ev);
  return Math.max(0, ev.spotlight_slot_count - used);
}

function computePackageHeldCount(ev: EventRec, package_id: string): number {
  let held = 0;
  for (const app of ev.applications.values()) {
    if (app.package_id === package_id && app.status === "SUBMITTED" && app.hold_status === "HELD") held += 1;
  }
  return held;
}

function computePackageWaitlistExists(ev: EventRec, package_id: string): boolean {
  for (const app of ev.applications.values()) {
    if (app.package_id === package_id && app.status === "SUBMITTED" && app.hold_status === "WAITLISTED") return true;
  }
  return false;
}

function computePackageCommitmentCount(ev: EventRec, package_id: string): number {
  let cnt = 0;
  for (const c of ev.commitments.values()) {
    if (c.package_id === package_id && c.status !== "RESCINDED") cnt += 1;
  }
  return cnt;
}

function computePackageSlotsRemaining(ev: EventRec, pkg: PackageRec): number {
  const commitments = computePackageCommitmentCount(ev, pkg.id);
  const held = computePackageHeldCount(ev, pkg.id);
  return Math.max(0, pkg.slot_count - commitments - held);
}

function includedBenefitMap(included: IncludedBenefit[]): Map<BenefitKind, number> {
  const m = new Map<BenefitKind, number>();
  for (const b of included) m.set(b.benefit_kind, (m.get(b.benefit_kind) ?? 0) + b.quantity);
  return m;
}

function computeCommitmentBenefitsLeft(ev: EventRec, comm: CommitmentRec): Record<BenefitKind, number> {
  const pkg = getPackage(ev, comm.package_id);
  const included = includedBenefitMap(pkg.included_benefits);

  const finalizedUsed = new Map<BenefitKind, number>();
  for (const claimId of comm.claim_ids) {
    const cl = ev.claims.get(claimId);
    if (!cl) continue;
    if (cl.status !== "FINALIZED") continue;
    finalizedUsed.set(cl.benefit_kind, (finalizedUsed.get(cl.benefit_kind) ?? 0) + cl.quantity);
  }

  const out: Record<BenefitKind, number> = {
    LEAD_SCANS: 0,
    STAGE_MINUTES: 0,
    SPOTLIGHT: 0,
  };

  for (const k of benefitKinds()) {
    const inc = included.get(k) ?? 0;
    const used = finalizedUsed.get(k) ?? 0;
    out[k] = Math.max(0, inc - used);
  }
  return out;
}

function commitmentHasNonVoidedSpotlight(ev: EventRec, comm: CommitmentRec): boolean {
  for (const claimId of comm.claim_ids) {
    const cl = ev.claims.get(claimId);
    if (!cl) continue;
    if (cl.benefit_kind === "SPOTLIGHT" && cl.status !== "VOIDED") return true;
  }
  return false;
}

function commitmentHasFinalizedClaims(ev: EventRec, comm: CommitmentRec): boolean {
  for (const claimId of comm.claim_ids) {
    const cl = ev.claims.get(claimId);
    if (!cl) continue;
    if (cl.status === "FINALIZED") return true;
  }
  return false;
}

function eventView(ev: EventRec) {
  return {
    id: ev.id,
    name: ev.name,
    spotlight_slot_count: ev.spotlight_slot_count,
    posture: ev.posture,
    ops_run_index: ev.ops_run_index,
    spotlight_slots_remaining: computeEventSpotlightRemaining(ev),
    version: ev.version,
  };
}

function packageView(ev: EventRec, pkg: PackageRec) {
  return {
    id: pkg.id,
    label: pkg.label,
    price_cents: pkg.price_cents,
    slot_count: pkg.slot_count,
    included_benefits: pkg.included_benefits,
    status: pkg.status,
    slots_remaining: computePackageSlotsRemaining(ev, pkg),
    version: pkg.version,
  };
}

function sponsorView(s: SponsorRec) {
  return {
    id: s.id,
    display_name: s.display_name,
    legal_name: s.legal_name ?? null,
    primary_contact_email: s.primary_contact_email,
    status: s.status,
    version: s.version,
  };
}

function applicationView(a: ApplicationRec) {
  return {
    id: a.id,
    sponsor_id: a.sponsor_id,
    package_id: a.package_id,
    status: a.status,
    note: a.note ?? null,
    submit_seq: a.submit_seq,
    hold_status: a.hold_status,
    hold_expires_on_ops: a.hold_expires_on_ops,
    commitment_id: a.commitment_id,
    version: a.version,
  };
}

function claimView(cl: ClaimRec) {
  return {
    id: cl.id,
    commitment_id: cl.commitment_id,
    benefit_kind: cl.benefit_kind,
    quantity: cl.quantity,
    status: cl.status,
    version: cl.version,
  };
}

function commitmentView(ev: EventRec, comm: CommitmentRec) {
  const claims = comm.claim_ids
    .map((id) => ev.claims.get(id))
    .filter((c): c is ClaimRec => !!c)
    .map((c) => ({
      id: c.id,
      benefit_kind: c.benefit_kind,
      quantity: c.quantity,
      status: c.status,
      version: c.version,
    }));
  return {
    id: comm.id,
    sponsor_id: comm.sponsor_id,
    package_id: comm.package_id,
    application_id: comm.application_id,
    status: comm.status,
    activation_deadline_on_ops: comm.activation_deadline_on_ops,
    benefits_left: computeCommitmentBenefitsLeft(ev, comm),
    claims,
    version: comm.version,
  };
}

function withdrawApplication(ev: EventRec, app: ApplicationRec) {
  if (app.status === "WITHDRAWN" || app.status === "REJECTED" || app.status === "EXPIRED" || app.status === "APPROVED") {
    err(409, "ERR_INVALID_STATE", "Application is not withdrawable.");
  }
  app.status = "WITHDRAWN";
  app.hold_status = null;
  app.hold_expires_on_ops = null;
  app.version += 1;
}

function voidClaim(ev: EventRec, cl: ClaimRec) {
  if (cl.status === "VOIDED") return;
  cl.status = "VOIDED";
  cl.version += 1;
}

function rescindCommitment(ev: EventRec, comm: CommitmentRec, mode: "polite" | "force") {
  if (comm.status === "RESCINDED") err(409, "ERR_INVALID_STATE", "Commitment already rescinded.");

  if (mode === "polite") {
    if (commitmentHasFinalizedClaims(ev, comm)) err(409, "ERR_HAS_FINALIZED_CLAIMS", "Commitment has finalized claims; void them first.");
  }

  comm.status = "RESCINDED";
  comm.activation_deadline_on_ops = null;
  comm.version += 1;

  for (const claimId of comm.claim_ids) {
    const cl = ev.claims.get(claimId);
    if (!cl) continue;
    if (mode === "force") {
      voidClaim(ev, cl);
    } else {
      if (cl.status === "PROPOSED") voidClaim(ev, cl);
    }
  }
}

function suspendActiveCommitmentsForWatchlist(ev: EventRec, sponsor_id: string) {
  for (const comm of ev.commitments.values()) {
    if (comm.sponsor_id !== sponsor_id) continue;
    if (comm.status !== "ACTIVE") continue;
    comm.status = "SUSPENDED";
    comm.activation_deadline_on_ops = ev.ops_run_index + ACTIVATION_TTL_OPS;
    comm.version += 1;
  }
}

function blockSponsorCascade(ev: EventRec, sponsor_id: string) {
  for (const app of ev.applications.values()) {
    if (app.sponsor_id !== sponsor_id) continue;
    if (app.status === "DRAFT" || app.status === "SUBMITTED") {
      app.status = "WITHDRAWN";
      app.hold_status = null;
      app.hold_expires_on_ops = null;
      app.version += 1;
    }
  }

  for (const comm of ev.commitments.values()) {
    if (comm.sponsor_id !== sponsor_id) continue;
    if (comm.status === "RESCINDED") continue;
    comm.status = "RESCINDED";
    comm.activation_deadline_on_ops = null;
    comm.version += 1;

    for (const claimId of comm.claim_ids) {
      const cl = ev.claims.get(claimId);
      if (!cl) continue;
      voidClaim(ev, cl);
    }
  }
}

function validateEmailBasic(v: unknown): string {
  if (!isNonEmptyString(v)) err(400, "ERR_BAD_REQUEST", "primary_contact_email is required.");
  const s = v.trim();
  if (s.length > 320) err(400, "ERR_BAD_REQUEST", "primary_contact_email is too long.");
  const at = s.indexOf("@");
  if (at <= 0 || at === s.length - 1) err(400, "ERR_BAD_REQUEST", "primary_contact_email is invalid.");
  return s;
}

function runOps(ev: EventRec) {
  ev.ops_run_index += 1;
  ev.version += 1;

  let expiredCount = 0;
  for (const app of ev.applications.values()) {
    if (app.status !== "SUBMITTED") continue;
    if (app.hold_status !== "HELD") continue;
    if (app.hold_expires_on_ops === null) continue;
    if (app.hold_expires_on_ops <= ev.ops_run_index) {
      app.status = "EXPIRED";
      app.hold_status = null;
      app.hold_expires_on_ops = null;
      app.version += 1;
      expiredCount += 1;
    }
  }

  let revokedCommitments = 0;
  let voidedClaims = 0;
  for (const comm of ev.commitments.values()) {
    if (comm.status === "PENDING_COUNTERSIGN" || comm.status === "SUSPENDED") {
      if (comm.activation_deadline_on_ops !== null && comm.activation_deadline_on_ops <= ev.ops_run_index) {
        comm.status = "RESCINDED";
        comm.activation_deadline_on_ops = null;
        comm.version += 1;
        revokedCommitments += 1;

        for (const claimId of comm.claim_ids) {
          const cl = ev.claims.get(claimId);
          if (!cl) continue;
          if (cl.status !== "VOIDED") {
            cl.status = "VOIDED";
            cl.version += 1;
            voidedClaims += 1;
          }
        }
      }
    }
  }

  let advancedCount = 0;
  for (const pkg of ev.packages.values()) {
    if (pkg.status !== "ACTIVE") continue;

    const slotsFree = computePackageSlotsRemaining(ev, pkg);
    if (slotsFree <= 0) continue;

    const waitlisted = Array.from(ev.applications.values())
      .filter((a) => a.package_id === pkg.id && a.status === "SUBMITTED" && a.hold_status === "WAITLISTED")
      .sort((a, b) => (a.submit_seq ?? Number.MAX_SAFE_INTEGER) - (b.submit_seq ?? Number.MAX_SAFE_INTEGER));

    let granted = 0;
    for (const a of waitlisted) {
      if (granted >= slotsFree) break;
      a.hold_status = "HELD";
      a.hold_expires_on_ops = ev.ops_run_index + HOLD_TTL_OPS;
      a.version += 1;
      advancedCount += 1;
      granted += 1;
    }
  }

  return { expired_holds: expiredCount, revoked_commitments: revokedCommitments, voided_claims: voidedClaims, advanced_waitlist: advancedCount };
}

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "1mb" }));

app.use((req, res, next) => {
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  next();
});

app.get("/health", (req, res) => {
  sendSuccess(res, 200, { ok: true });
});

app.post("/events", (req, res, next) => {
  try {
    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { name, spotlight_slot_count } = req.body;

    if (!isNonEmptyString(name)) err(400, "ERR_BAD_REQUEST", "name is required.");
    if (!isNonNegativeInt(spotlight_slot_count)) err(400, "ERR_BAD_REQUEST", "spotlight_slot_count must be a non-negative integer.");

    const ev: EventRec = {
      id: genId("evt"),
      name: name.trim(),
      spotlight_slot_count,
      posture: "DRAFT",
      ops_run_index: 0,
      version: 1,
      packages: new Map(),
      sponsors: new Map(),
      applications: new Map(),
      commitments: new Map(),
      claims: new Map(),
    };
    db.events.set(ev.id, ev);
    sendSuccess(res, 201, eventView(ev));
  } catch (e) {
    next(e);
  }
});

app.get("/events/:event_id", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    sendSuccess(res, 200, eventView(ev));
  } catch (e) {
    next(e);
  }
});

app.patch("/events/:event_id", (req, res, next) => {
  try {

    const ifMatch = requireIfMatch(req);

    const ev = getEvent(req.params.event_id);

    if (ev.version !== ifMatch) err(409, "ERR_VERSION_CONFLICT", "Version conflict.");

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { name, posture, spotlight_slot_count } = req.body;

    if (name !== undefined) {
      if (!isNonEmptyString(name)) err(400, "ERR_BAD_REQUEST", "name must be a non-empty string.");
      ev.name = name.trim();
    }

    if (spotlight_slot_count !== undefined) {
      if (!isNonNegativeInt(spotlight_slot_count)) err(400, "ERR_BAD_REQUEST", "spotlight_slot_count must be a non-negative integer.");
      const used = computeEventSpotlightUsed(ev);
      if (spotlight_slot_count < used) err(409, "ERR_SPOTLIGHT_IN_USE", "spotlight_slot_count cannot be less than already finalized Spotlight claims.");
      ev.spotlight_slot_count = spotlight_slot_count;
    }

    if (posture !== undefined) {
      if (!isNonEmptyString(posture)) err(400, "ERR_BAD_REQUEST", "posture must be a string.");
      const allowed: EventPosture[] = ["DRAFT", "OPEN", "LOCKDOWN", "ARCHIVED"];
      if (!allowed.includes(posture as EventPosture)) err(400, "ERR_BAD_REQUEST", "Invalid posture.");
      const newPosture = posture as EventPosture;

      if (ev.posture === "ARCHIVED" && newPosture !== "ARCHIVED") {
        err(409, "ERR_INVALID_STATE", "Cannot change posture of archived event");
      }
      if (ev.posture === "OPEN" && newPosture === "DRAFT") {
        err(409, "ERR_INVALID_STATE", "Cannot rewind event to DRAFT");
      }
      ev.posture = newPosture;
    }

    ev.version += 1;
    sendSuccess(res, 200, eventView(ev));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/run_ops", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const summary = runOps(ev);
    sendSuccess(res, 200, { event: eventView(ev), summary });
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/packages", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    assertEventNotLockedForCreation(ev);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { label, price_cents, slot_count, included_benefits } = req.body;

    if (!isNonEmptyString(label)) err(400, "ERR_BAD_REQUEST", "label is required.");
    if (!isNonNegativeInt(price_cents)) err(400, "ERR_BAD_REQUEST", "price_cents must be a non-negative integer.");
    if (!isPositiveInt(slot_count)) err(400, "ERR_BAD_REQUEST", "slot_count must be a positive integer.");

    if (!Array.isArray(included_benefits)) err(400, "ERR_BAD_REQUEST", "included_benefits must be an array.");
    const parsedBenefits: IncludedBenefit[] = [];
    for (const entry of included_benefits) {
      if (!isRecord(entry)) err(400, "ERR_BAD_REQUEST", "included_benefits entries must be objects.");
      const bk = entry.benefit_kind;
      const q = entry.quantity;
      if (!isBenefitKind(bk)) err(400, "ERR_BAD_REQUEST", "Invalid benefit_kind.");
      if (!isPositiveInt(q)) err(400, "ERR_BAD_REQUEST", "Benefit quantity must be a positive integer.");
      if (bk === "SPOTLIGHT" && q !== 1) err(400, "ERR_BAD_REQUEST", "SPOTLIGHT included benefit quantity must be 1.");
      parsedBenefits.push({ benefit_kind: bk, quantity: q });
    }

    const pkg: PackageRec = {
      id: genId("pkg"),
      label: label.trim(),
      price_cents,
      slot_count,
      included_benefits: parsedBenefits,
      status: "ACTIVE",
      version: 1,
      submit_seq_counter: 0,
    };
    ev.packages.set(pkg.id, pkg);

    sendSuccess(res, 201, packageView(ev, pkg));
  } catch (e) {
    next(e);
  }
});

app.get("/events/:event_id/packages/:package_id", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const pkg = getPackage(ev, req.params.package_id);
    sendSuccess(res, 200, packageView(ev, pkg));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/packages/:package_id/transition", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const pkg = getPackage(ev, req.params.package_id);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { action } = req.body;
    if (!isNonEmptyString(action)) err(400, "ERR_BAD_REQUEST", "action is required.");

    if (action === "RETIRE") {
      if (pkg.status === "RETIRED") err(409, "ERR_INVALID_STATE", "Package already retired.");
      pkg.status = "RETIRED";
      pkg.version += 1;

      for (const appRec of ev.applications.values()) {
        if (appRec.package_id !== pkg.id) continue;
        if (appRec.status !== "SUBMITTED") continue;
        if (appRec.hold_status === "HELD") {
          appRec.hold_status = "WAITLISTED";
          appRec.hold_expires_on_ops = null;
          appRec.version += 1;
        }
      }

      sendSuccess(res, 200, packageView(ev, pkg));
      return;
    }

    if (action === "REACTIVATE") {
      assertEventNotLockedForCreation(ev);
      if (pkg.status === "ACTIVE") err(409, "ERR_INVALID_STATE", "Package already active.");
      pkg.status = "ACTIVE";
      pkg.version += 1;
      sendSuccess(res, 200, packageView(ev, pkg));
      return;
    }

    err(400, "ERR_BAD_REQUEST", "Invalid action.");
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/sponsors", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    assertEventNotLockedForCreation(ev);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { display_name, legal_name, primary_contact_email, status } = req.body;

    if (!isNonEmptyString(display_name)) err(400, "ERR_BAD_REQUEST", "display_name is required.");
    const email = validateEmailBasic(primary_contact_email);

    let legal: string | undefined = undefined;
    if (legal_name !== undefined) {
      if (legal_name !== null && !isNonEmptyString(legal_name)) err(400, "ERR_BAD_REQUEST", "legal_name must be a non-empty string or omitted.");
      if (isNonEmptyString(legal_name)) legal = legal_name.trim();
    }

    let sponsorStatus: SponsorStatus = "PROSPECT";
    if (status !== undefined) {
      if (!isNonEmptyString(status)) err(400, "ERR_BAD_REQUEST", "status must be a non-empty string or omitted.");
      const allowed: SponsorStatus[] = ["PROSPECT", "VETTED", "WATCHLIST", "BLOCKED"];
      if (allowed.includes(status as SponsorStatus)) {
        sponsorStatus = status as SponsorStatus;
      }
    }

    const s: SponsorRec = {
      id: genId("spn"),
      display_name: display_name.trim(),
      legal_name: legal,
      primary_contact_email: email,
      status: sponsorStatus,
      version: 1,
    };
    ev.sponsors.set(s.id, s);
    sendSuccess(res, 201, sponsorView(s));
  } catch (e) {
    next(e);
  }
});

app.get("/events/:event_id/sponsors/:sponsor_id", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const s = getSponsor(ev, req.params.sponsor_id);
    sendSuccess(res, 200, sponsorView(s));
  } catch (e) {
    next(e);
  }
});

app.patch("/events/:event_id/sponsors/:sponsor_id", (req, res, next) => {
  try {

    const ifMatch = requireIfMatch(req);

    const ev = getEvent(req.params.event_id);
    const s = getSponsor(ev, req.params.sponsor_id);

    if (s.version !== ifMatch) err(409, "ERR_VERSION_CONFLICT", "Version conflict.");

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { display_name, legal_name, primary_contact_email, status } = req.body;

    const prevStatus = s.status;

    if (display_name !== undefined) {
      if (!isNonEmptyString(display_name)) err(400, "ERR_BAD_REQUEST", "display_name must be a non-empty string.");
      s.display_name = display_name.trim();
    }

    if (legal_name !== undefined) {
      if (legal_name === null) {
        s.legal_name = undefined;
      } else {
        if (!isNonEmptyString(legal_name)) err(400, "ERR_BAD_REQUEST", "legal_name must be a non-empty string or null.");
        s.legal_name = legal_name.trim();
      }
    }

    if (primary_contact_email !== undefined) {
      s.primary_contact_email = validateEmailBasic(primary_contact_email);
    }

    if (status !== undefined) {
      if (!isNonEmptyString(status)) err(400, "ERR_BAD_REQUEST", "status must be a string.");
      const allowed: SponsorStatus[] = ["PROSPECT", "VETTED", "WATCHLIST", "BLOCKED"];
      if (!allowed.includes(status as SponsorStatus)) err(400, "ERR_BAD_REQUEST", "Invalid status.");
      s.status = status as SponsorStatus;
    }

    s.version += 1;

    if (prevStatus !== "BLOCKED" && s.status === "BLOCKED") {
      blockSponsorCascade(ev, s.id);
    } else if (prevStatus !== "WATCHLIST" && s.status === "WATCHLIST") {
      suspendActiveCommitmentsForWatchlist(ev, s.id);
    }

    sendSuccess(res, 200, sponsorView(s));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/applications", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    assertEventNotLockedForCreation(ev);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { sponsor_id, package_id, note } = req.body;

    if (!isNonEmptyString(sponsor_id)) err(400, "ERR_BAD_REQUEST", "sponsor_id is required.");
    if (!isNonEmptyString(package_id)) err(400, "ERR_BAD_REQUEST", "package_id is required.");

    const s = getSponsor(ev, sponsor_id);
    assertSponsorNotBlocked(s);
    const pkg = getPackage(ev, package_id);
    if (pkg.status !== "ACTIVE") err(409, "ERR_PACKAGE_RETIRED", "Package is retired.");

    for (const a of ev.applications.values()) {
      if (a.sponsor_id === sponsor_id && a.package_id === package_id && (a.status === "DRAFT" || a.status === "SUBMITTED")) {
        err(409, "ERR_DUPLICATE_APPLICATION", "Duplicate non-terminal application for sponsor/package.");
      }
    }

    for (const c of ev.commitments.values()) {
      if (c.sponsor_id === sponsor_id && c.package_id === package_id && c.status !== "RESCINDED") {
        err(409, "ERR_DUPLICATE_COMMITMENT", "Sponsor already has a non-rescinded commitment for this package.");
      }
    }

    let nextNote: string | undefined = undefined;
    if (note !== undefined) {
      if (note !== null && !isNonEmptyString(note)) err(400, "ERR_BAD_REQUEST", "note must be a non-empty string or omitted.");
      if (isNonEmptyString(note)) nextNote = note.trim();
    }

    const appRec: ApplicationRec = {
      id: genId("app"),
      sponsor_id,
      package_id,
      status: "DRAFT",
      version: 1,
      note: nextNote,
      submit_seq: null,
      hold_status: null,
      hold_expires_on_ops: null,
      commitment_id: null,
    };
    ev.applications.set(appRec.id, appRec);

    sendSuccess(res, 201, applicationView(appRec));
  } catch (e) {
    next(e);
  }
});

app.get("/events/:event_id/applications/:application_id", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const a = getApplication(ev, req.params.application_id);
    sendSuccess(res, 200, applicationView(a));
  } catch (e) {
    next(e);
  }
});

app.put("/events/:event_id/applications/:application_id", (req, res, next) => {
  try {

    const ifMatch = requireIfMatch(req);

    const ev = getEvent(req.params.event_id);
    const a = getApplication(ev, req.params.application_id);

    if (a.version !== ifMatch) err(409, "ERR_VERSION_CONFLICT", "Version conflict.");

    assertEventNotLockedForCreation(ev);

    if (a.status !== "DRAFT") err(409, "ERR_INVALID_STATE", "Only DRAFT applications can be edited.");

    const s = getSponsor(ev, a.sponsor_id);
    assertSponsorNotBlocked(s);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { note } = req.body;

    if (note !== undefined) {
      if (note === null) {
        a.note = undefined;
      } else {
        if (!isNonEmptyString(note)) err(400, "ERR_BAD_REQUEST", "note must be a non-empty string or null.");
        a.note = note.trim();
      }
    }

    a.version += 1;
    sendSuccess(res, 200, applicationView(a));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/applications/:application_id/transition", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const a = getApplication(ev, req.params.application_id);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { action } = req.body;
    if (!isNonEmptyString(action)) err(400, "ERR_BAD_REQUEST", "action is required.");

    if (action === "WITHDRAW") {
      withdrawApplication(ev, a);
      sendSuccess(res, 200, applicationView(a));
      return;
    }

    if (action === "SUBMIT") {
      assertEventOpenForProgress(ev);

      if (a.status !== "DRAFT") err(409, "ERR_INVALID_STATE", "Only DRAFT applications can be submitted.");

      const s = getSponsor(ev, a.sponsor_id);
      assertSponsorNotBlocked(s);

      const pkg = getPackage(ev, a.package_id);
      if (pkg.status !== "ACTIVE") err(409, "ERR_PACKAGE_RETIRED", "Package is retired.");

      for (const other of ev.applications.values()) {
        if (other.id === a.id) continue;
        if (other.sponsor_id === a.sponsor_id && other.package_id === a.package_id && (other.status === "DRAFT" || other.status === "SUBMITTED")) {
          err(409, "ERR_DUPLICATE_APPLICATION", "Duplicate non-terminal application for sponsor/package.");
        }
      }

      for (const c of ev.commitments.values()) {
        if (c.sponsor_id === a.sponsor_id && c.package_id === a.package_id && c.status !== "RESCINDED") {
          err(409, "ERR_DUPLICATE_COMMITMENT", "Sponsor already has a non-rescinded commitment for this package.");
        }
      }

      const waitlistExists = computePackageWaitlistExists(ev, pkg.id);
      const slotsRemaining = computePackageSlotsRemaining(ev, pkg);

      a.status = "SUBMITTED";
      a.submit_seq = ++pkg.submit_seq_counter;

      if (waitlistExists) {
        a.hold_status = "WAITLISTED";
        a.hold_expires_on_ops = null;
      } else {
        if (slotsRemaining > 0) {
          a.hold_status = "HELD";
          a.hold_expires_on_ops = ev.ops_run_index + HOLD_TTL_OPS;
        } else {
          a.hold_status = "WAITLISTED";
          a.hold_expires_on_ops = null;
        }
      }

      a.version += 1;
      sendSuccess(res, 200, applicationView(a));
      return;
    }

    if (action === "REJECT") {
      if (a.status !== "SUBMITTED") err(409, "ERR_INVALID_STATE", "Only SUBMITTED applications can be rejected.");
      const s = getSponsor(ev, a.sponsor_id);
      assertSponsorNotBlocked(s);

      a.status = "REJECTED";
      a.hold_status = null;
      a.hold_expires_on_ops = null;
      a.version += 1;

      sendSuccess(res, 200, applicationView(a));
      return;
    }

    if (action === "APPROVE") {
      assertEventOpenForProgress(ev);

      if (a.status !== "SUBMITTED") err(409, "ERR_INVALID_STATE", "Only SUBMITTED applications can be approved.");
      if (a.hold_status !== "HELD") err(409, "ERR_NO_ACTIVE_HOLD", "Application does not have an active hold.");

      const s = getSponsor(ev, a.sponsor_id);
      assertSponsorNotBlocked(s);

      const pkg = getPackage(ev, a.package_id);
      if (pkg.status !== "ACTIVE") err(409, "ERR_PACKAGE_RETIRED", "Package is retired.");

      for (const c of ev.commitments.values()) {
        if (c.sponsor_id === a.sponsor_id && c.package_id === a.package_id && c.status !== "RESCINDED") {
          err(409, "ERR_DUPLICATE_COMMITMENT", "Sponsor already has a non-rescinded commitment for this package.");
        }
      }

      const comm: CommitmentRec = {
        id: genId("cmt"),
        sponsor_id: a.sponsor_id,
        package_id: a.package_id,
        application_id: a.id,
        status: "PENDING_COUNTERSIGN",
        version: 1,
        activation_deadline_on_ops: ev.ops_run_index + ACTIVATION_TTL_OPS,
        claim_ids: [],
      };

      if (s.status === "VETTED") {
        comm.status = "ACTIVE";
        comm.activation_deadline_on_ops = null;
      } else if (s.status === "WATCHLIST") {
        comm.status = "SUSPENDED";
        comm.activation_deadline_on_ops = ev.ops_run_index + ACTIVATION_TTL_OPS;
      } else {
        comm.status = "PENDING_COUNTERSIGN";
        comm.activation_deadline_on_ops = ev.ops_run_index + ACTIVATION_TTL_OPS;
      }

      ev.commitments.set(comm.id, comm);

      a.status = "APPROVED";
      a.hold_status = null;
      a.hold_expires_on_ops = null;
      a.commitment_id = comm.id;
      a.version += 1;

      sendSuccess(res, 200, { application: applicationView(a), commitment: commitmentView(ev, comm) });
      return;
    }

    err(400, "ERR_BAD_REQUEST", "Invalid action.");
  } catch (e) {
    next(e);
  }
});

app.get("/events/:event_id/commitments/:commitment_id", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const comm = getCommitment(ev, req.params.commitment_id);
    sendSuccess(res, 200, commitmentView(ev, comm));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/commitments/:commitment_id/transition", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const comm = getCommitment(ev, req.params.commitment_id);
    const sponsor = getSponsor(ev, comm.sponsor_id);

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { action } = req.body;
    if (!isNonEmptyString(action)) err(400, "ERR_BAD_REQUEST", "action is required.");

    if (action === "RESCIND") {

      rescindCommitment(ev, comm, "polite");
      sendSuccess(res, 200, commitmentView(ev, comm));
      return;
    }

    if (action === "COUNTERSIGN") {
      assertEventOpenForProgress(ev);
      assertSponsorNotBlocked(sponsor);

      if (comm.status !== "PENDING_COUNTERSIGN" && comm.status !== "SUSPENDED") {
        err(409, "ERR_INVALID_STATE", "Only PENDING_COUNTERSIGN or SUSPENDED commitments can be countersigned.");
      }

      comm.status = "ACTIVE";
      comm.activation_deadline_on_ops = null;
      comm.version += 1;

      sendSuccess(res, 200, commitmentView(ev, comm));
      return;
    }

    err(400, "ERR_BAD_REQUEST", "Invalid action.");
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/commitments/:commitment_id/claims", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    assertEventOpenForProgress(ev);

    const comm = getCommitment(ev, req.params.commitment_id);
    const sponsor = getSponsor(ev, comm.sponsor_id);
    assertSponsorNotBlocked(sponsor);

    if (comm.status !== "ACTIVE") err(409, "ERR_COMMITMENT_NOT_ACTIVE", "Commitment is not active.");

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { benefit_kind, quantity } = req.body;

    if (!isBenefitKind(benefit_kind)) err(400, "ERR_BAD_REQUEST", "benefit_kind is required and must be valid.");
    if (!isPositiveInt(quantity)) err(400, "ERR_BAD_REQUEST", "quantity must be a positive integer.");

    const pkg = getPackage(ev, comm.package_id);
    const included = includedBenefitMap(pkg.included_benefits);
    if (!included.has(benefit_kind)) err(409, "ERR_BENEFIT_NOT_INCLUDED", "Benefit kind not included in package.");

    if (benefit_kind === "SPOTLIGHT") {
      if (quantity !== 1) err(400, "ERR_BAD_REQUEST", "SPOTLIGHT claim quantity must be 1.");
      if (commitmentHasNonVoidedSpotlight(ev, comm)) err(409, "ERR_DUPLICATE_CLAIM", "Spotlight is already in use for this commitment.");
    }

    const cl: ClaimRec = {
      id: genId("clm"),
      commitment_id: comm.id,
      benefit_kind,
      quantity,
      status: "PROPOSED",
      version: 1,
    };

    ev.claims.set(cl.id, cl);
    comm.claim_ids.push(cl.id);
    comm.version += 1;

    sendSuccess(res, 201, claimView(cl));
  } catch (e) {
    next(e);
  }
});

app.post("/events/:event_id/commitments/:commitment_id/claims/:claim_id/transition", (req, res, next) => {
  try {
    const ev = getEvent(req.params.event_id);
    const comm = getCommitment(ev, req.params.commitment_id);
    const cl = getClaim(ev, req.params.claim_id);

    if (cl.commitment_id !== comm.id) err(404, "ERR_NOT_FOUND", "Claim not found under this commitment.");

    if (!isRecord(req.body)) err(400, "ERR_BAD_REQUEST", "Invalid JSON body.");
    const { action } = req.body;
    if (!isNonEmptyString(action)) err(400, "ERR_BAD_REQUEST", "action is required.");

    if (action === "VOID") {

      if (cl.status === "VOIDED") err(409, "ERR_INVALID_STATE", "Claim already voided.");
      cl.status = "VOIDED";
      cl.version += 1;
      sendSuccess(res, 200, claimView(cl));
      return;
    }

    if (action === "FINALIZE") {
      assertEventOpenForProgress(ev);

      const sponsor = getSponsor(ev, comm.sponsor_id);
      assertSponsorNotBlocked(sponsor);

      if (comm.status !== "ACTIVE") err(409, "ERR_COMMITMENT_NOT_ACTIVE", "Commitment is not active.");
      if (cl.status !== "PROPOSED") err(409, "ERR_INVALID_STATE", "Only PROPOSED claims can be finalized.");

      const pkg = getPackage(ev, comm.package_id);
      const included = includedBenefitMap(pkg.included_benefits);
      if (!included.has(cl.benefit_kind)) err(409, "ERR_BENEFIT_NOT_INCLUDED", "Benefit kind not included in package.");

      if (cl.benefit_kind === "SPOTLIGHT") {
        if (cl.quantity !== 1) err(400, "ERR_BAD_REQUEST", "SPOTLIGHT claim quantity must be 1.");

        for (const claimId of comm.claim_ids) {
          if (claimId === cl.id) continue;
          const other = ev.claims.get(claimId);
          if (!other) continue;
          if (other.benefit_kind === "SPOTLIGHT" && other.status !== "VOIDED") err(409, "ERR_DUPLICATE_CLAIM", "Spotlight is already in use for this commitment.");
        }

        const remaining = computeEventSpotlightRemaining(ev);
        if (remaining <= 0) err(409, "ERR_SPOTLIGHT_FULL", "No spotlight slots remaining for this event.");
      }

      const left = computeCommitmentBenefitsLeft(ev, comm);
      if (cl.quantity > left[cl.benefit_kind]) err(409, "ERR_INSUFFICIENT_BENEFIT", "Insufficient benefit remaining.");

      cl.status = "FINALIZED";
      cl.version += 1;

      sendSuccess(res, 200, claimView(cl));
      return;
    }

    err(400, "ERR_BAD_REQUEST", "Invalid action.");
  } catch (e) {
    next(e);
  }
});

app.use((e: any, req: Request, res: Response, next: NextFunction) => {
  if (e && typeof e === "object" && "type" in e && (e as any).type === "entity.parse.failed") {
    sendError(res, 400, "ERR_BAD_REQUEST", "Malformed JSON.");
    return;
  }
  next(e);
});

app.use((req, res) => {
  sendError(res, 404, "ERR_NOT_FOUND", "Route not found.");
});

app.use((e: any, req: Request, res: Response, next: NextFunction) => {
  if (e instanceof ApiErr) {
    sendError(res, e.status, e.code, e.message);
    return;
  }
  sendError(res, 500, "ERR_BAD_REQUEST", "Internal server error.");
});

const port = Number(process.env.PORT) || 3000;
app.listen(port, () => {

  console.log(`SponsorshipOps API listening on ${port}`);
});
