# Worklog — task_1760_contents_pack_out_restoration_storage

## Step 1: Create Task Directory — 2026-08-14T00:00:00.000Z

Task directory `tasks/task_1760_contents_pack_out_restoration_storage/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; no index scan performed, no other task directory touched.

Difficulty directive from user: "Generate task hard than expert level!" → scaffold generation instructed to target the Expert band (§0.4) at its upper bounds (entity count 12–15, endpoints toward 32, error catalog toward 30, 4+ cross-cutting gates, dense state machines with cycles/parallel dimensions), maximizing coupling density rather than volume.

## Step 2: Generate Scaffold — 2026-08-14T15:08:00.000Z

All three scaffold artifacts are complete and verified. Final summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/SCAFFOLD.yaml` (§1.0–§1.7 only — no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

(The pre-existing `worklog.md` / `workspace/` in that directory were pipeline-created before my run; untouched.)

## Counts
- **Entities: 14** — PackOutJob, Room, Item, DisposalRecord, CleaningTask, Vault, StoragePlacement, Subcontractor, SpecialtyReferral, CustodyEvent (append-only, `common_fields: false`), HandlingClaim, PackBackSchedule, StorageStatement (self-referential supersede FK), CarrierInvoice
- **Endpoints: 44** — above the 28–32 aspiration deliberately: 17 FKs each carry a lint-mandated reverse-reachability GET, and 14 coupled entities require their own create/transition surfaces; §0.4 explicitly ranks these counts as guidelines behind coupling density
- **Error codes: 28** (all 28 mechanically verified triggerable by a §1.8/§1.9 instance)
- **State machines: 13** — 7 cyclic (structure sign-off rescind, Item triage loop, CleaningTask rework, SpecialtyReferral resend, HandlingClaim appeal, PackBackSchedule reschedule, CarrierInvoice dispute→resubmit); parallel dimensions on Item (`condition_triage × processing_status`) and PackOutJob (`status × structure_status`); compound derivations on Room.status and PackOutJob.billing_status
- **Difficulty layers (§0.2): 4** — dual_variant_calculation, cascading_side_effects, optimistic_concurrency (2 OCC rules, both pass the serial-observability filter), ops_run_checkpoint; plus version-pinning of claim credit at invoice SUBMIT as a mechanism
- **Cross-cutting gates: 6** — structure-completion → pack-back, open-claim → pack-back, PROVISIONAL-statement → invoice creation, zero-balance → reconcile, QA_ACCEPTED-referral → high-value placement, hazmat/climate/capacity → placement

## Design indices
- **§1.8: 20 instances** — 2 per rule for all nine §0.5 rules, plus a 3rd for `boundary_precision_check` (exact-fit cu-ft / ≥1M-cent high-value / empty eligible set) and `cross_entity_state_dependency` (schedule→job, placement→item, schedule→claim). Differentiation honored: dual-variant on statements vs claims; combinatorial modes (b) rounding-order and (c) subtotal-keyed fee tier; cascades depth 4 (disposal re-triage) vs depth 3 (claim settle) from different triggers; priority pairs state-vs-fiscal and safety-vs-constraint; overlap semantics half-open-window vs aggregate-count; conserved quantities physical volume vs monetary credit. All numeric asserts pre-computed as literals (4137, 591, 7000/107000, 50000/100000, 11501, …).
- **§1.9: 37 instances (34 active + 3 `excluded_because` stubs)** across 8 sections; stubs cite real §1.8 instance names.

## Verification
`scaffold_lint.py` verdict, verbatim: **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (502 calls scanned). Additionally audited: 57 unique instance names across both files, zero unbound `${var}` placeholders, zero dangling `grounds:` references, all OCC payloads use `${var}` (never literals), no forbidden concurrency vocabulary, and the file-split rule honored. No sibling task under `tasks/` was read at any point.

Orchestrator verification: all three files exist (SCAFFOLD.yaml 1038 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 733 lines, SCAFFOLD_CORNER_DESIGN.yaml 671 lines) and parse as valid YAML.

## Step 3: Copy Shared Files — 2026-08-14T15:09:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `tasks/task_1760_contents_pack_out_restoration_storage/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-14T15:20:00.000Z

PRD generation is complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/workspace/PRD.md` (292 lines).

### PRD Section List
- **§1 Introduction** — 3 paragraphs (business context, operator populations, entity topology + dual-variant financials)
- **§2 Global Specifications** — 8 subsections: 2.1 RBAC (all 6 roles, identity semantics for opaque vs entity-backed `SubcontractorContact`, SoD rules), 2.2 API Response Structure (verbatim fixed block, confirmed byte-identical incl. `req_RANDOMALPHANUM123456`, `2025-05-24T10:30:00.123Z`, `UNIQUE_ERROR_IDENTIFIER_STRING`, `"data": { }`), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Identity/Timestamps/Logical Clock (UUID, ISO 8601 3-fractional-digits, version semantics, CustodyEvent's absent `updated_at`/`version`, clock default `2026-08-01T00:00:00Z`), 2.5 Precision & Rounding (incl. the pinned daily-rate-then-days order with the 6001→197/day→591-not-592 worked example), 2.6 OCC (both rules with exact error ids and 412 status), 2.7 Nested validation left-to-right + full 12-tier error precedence ordering, 2.8 Derived rollups & compensating invariants
- **§3 Business Logic** — 9 subsections organized by lifecycle: 3.1 job/room/item intake, 3.2 triage loop & disposal pipeline, 3.3 cleaning/rework & specialty referral/custody chain, 3.4 vault placement gates, 3.5 structure sign-off & pack-back, 3.6 claims (ACV/RCV variants), 3.7 statements & billing run (provisional whole-month vs final daily proration), 3.8 carrier invoices (tiered fee, credit pinning, dispute/reconcile), 3.9 job closure
- **§4 Endpoint Definitions** — 44-row table, 4 columns only (Method, Path, Description, Authorized Roles)
- **§5 Error Code Catalogue** — 28-row table, 2 columns only (Error ID, HTTP Status)

### Scaffold Table Rendering (§1.1–§1.7)
- **§1.1 Entities** (13 entities, 90 fields) — rendered as narrative in §3 lifecycle subsections with computed/rollup fields (`billing_status`, `accrued_storage_total_cents`, `occupied_cu_ft`, `posture`, `item_count`, `is_high_value`, room compound status) concentrated in §2.8 and entity-owning subsections
- **§1.2 State machines** (12 machines, all transitions) — rendered as state-pair prose in §3 (`INTAKE → ACTIVE`, `FILED → UNDER_REVIEW → APPROVED → SETTLED`, cyclic loops for re-triage, rework, resend, appeal, reschedule, dispute-resubmit), every precondition paired with its error id, every side effect stated
- **§1.3 Calculations** (7 rules) — all expressed as precise prose passing the reconstruction test: storage accrual both variants, ACV (10%/yr, 70% cap, 30% floor, nested max), RCV (250000-cent cap with QA_ACCEPTED exception), tiered invoice fee (5/7/9% keyed on pre-fee subtotal with pinned evaluation order), vault occupancy conservation, cleaning fee (12000+4000), specialty markup (default 15, round-once), eligibility count predicate
- **§1.4 Validations** (28 rules) — priority ordering rendered explicitly in §2.7 as a twelve-tier precedence narrative; each check paired with its error id near the workflow it guards in §3
- **§1.5 Endpoints** (44) — full table in §4; side effects scattered into §3 narratives
- **§1.6 Errors** (28) — two-column §5 table; trigger conditions only in §2/§3 prose
- **§1.7 Roles** (6) — §2.1 with exact spellings, identity translations, and exclusive/shared operation narrative

### Zero-Silence Rule Audit
Mechanical audit (backtick-coverage diff against scaffold, with fenced-code parity handled):
- **Contract 1 Field Coverage: PASS** — 90/90 entity fields, 55/55 request-body identifiers, 7/7 query params, 4/4 common fields, all present in backticks (3 initial gaps — `contact_email`, `referral_id`, `action` — were repaired into natural narrative homes)
- **Contract 2 Rule Coverage: PASS** — all 28 validations matchable to error ids, both OCC rules fully expressed (endpoint framing + `expected_item_version`/`expected_job_version` + exact error id + HTTP 412, no race framing), all state transitions with preconditions/side effects, all 7 calculations with constants and precision, all endpoint side effects and `applies_to` scopes, sibling branches symmetric (e.g. SALVAGEABLE vs NON_SALVAGEABLE triage arms, all 5 release reasons, all 4 release-reason cascades)
- **Contract 3 §3 Path Purity: PASS** — 536 backtick tokens scanned in §3; zero tokens starting with `/`, zero bare HTTP methods, zero method+path combos
- Aux checks: 28/28 error ids, 52/52 state values, 99/99 enum values, 6/6 role names, 44/44 endpoint paths present

### Design-Index Constraint Confirmation
Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, read, grepped, or referenced at any point. Only `SKILL.md`, `section-2.2-response-structure.md`, and `SCAFFOLD.yaml` were read.

## Step 6: Generate Implementation — 2026-08-14T15:39:00.000Z

Fresh boot shows empty state, the logical clock defaults to `2026-08-01T00:00:00.000Z`, request IDs start at 1, and the envelope matches the PRD spec. Implementation is complete.

### File list (line counts)

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 75 |
| `db.py` | 51 |
| `errors.py` | 151 |
| `response.py` | 54 |
| `middleware.py` | 65 |
| `helpers.py` | 280 |
| `routes/jobs.py` | 157 |
| `routes/items.py` | 176 |
| `routes/disposal.py` | 114 |
| `routes/cleaning.py` | 135 |
| `routes/vaults.py` | 56 |
| `routes/placements.py` | 159 |
| `routes/subcontractors.py` | 62 |
| `routes/referrals.py` | 260 |
| `routes/claims.py` | 191 |
| `routes/schedules.py` | 211 |
| `routes/billing.py` | 333 |
| `routes/clock.py` | 23 |
| `services/recompute.py` | 150 |
| `services/cascade.py` | 76 |
| **Total** | **2790** |

Plus `routes/__init__.py` and `services/__init__.py` (empty).

### Endpoint coverage: 44/44
Verified by counting `@bp.route` decorators — matches the PRD §4 endpoint table exactly (43 `/api/...` + 1 `/_clock/set_current_utc`).

### Error-code coverage: 28/28
Every PRD §5 catalog code has both a definition in `errors.py` and at least one `raise` call site in the routes/services. Verified programmatically.

### State-machine notes
- **PackOutJob.status** — INTAKE → ACTIVE (auto on first item), ACTIVE → PACKBACK_IN_PROGRESS (auto on first IN_TRANSIT schedule), →CLOSED (manual with 3 preconditions: all items terminal, no PROVISIONAL statements, no DRAFT/SUBMITTED/DISPUTED invoices).
- **PackOutJob.structure_status** — PENDING ⇄ IN_PROGRESS ⇄ COMPLETE cycle; RESCIND blocked while any schedule is CONFIRMED/IN_TRANSIT/DELIVERED.
- **Item** carries two parallel dimensions (`condition_triage`, `processing_status`) tracked independently per PRD §3.2. Triage is OCC-guarded via `expected_item_version`. NON_SALVAGEABLE triage fires the 4-link cascade (flip → auto-create DRAFT DisposalRecord → release ACTIVE placement with reason=DISPOSAL → vault decrement + accrual recompute).
- **DisposalRecord** — DRAFT → DOCUMENTED → VERIFIED with SoD (verifier ≠ documenter); auto-VOIDED if item re-triaged SALVAGEABLE before verification.
- **CleaningTask** — SCHEDULED → IN_PROGRESS → PASSED/FAILED, FAILED → IN_PROGRESS rework cycle increments `rework_count`; QA_PASS computes fee (12000 + 4000 if deodorization).
- **StoragePlacement** — ACTIVE → RELEASED with reasons MANUAL / DISPOSAL / CLAIM / SPECIALTY / PACK_BACK; release decrements vault occupancy and recomputes PROVISIONAL statement accrual + job accrued total.
- **SpecialtyReferral** — DRAFT → DISPATCHED → IN_CUSTODY → RETURNED → QA_ACCEPTED/QA_REJECTED, QA_REJECTED → DISPATCHED resend retains slot. Subcontractor capacity gates initial DISPATCH; capacity counter is recomputed from referrals in {DISPATCHED, IN_CUSTODY, QA_REJECTED}.
- **HandlingClaim** — FILED → UNDER_REVIEW → APPROVED/DENIED, DENIED → UNDER_REVIEW appeal loop, APPROVED → SETTLED (direct or invoice-sweep) / VOIDED. SoD enforced on APPROVE/DENY/SETTLE. Settlement: ACV uses nested min/max (10%/yr, 70% cap, 30% floor) via `Decimal` ROUND_HALF_UP; RCV caps at 250000 unless QA_ACCEPTED referral exists.
- **PackBackSchedule** — REQUESTED → CONFIRMED (4 gates: structure_status, crew-window overlap half-open, ≥1 eligible item, no open claims) → IN_TRANSIT → DELIVERED → COMPLETED; CONFIRMED → REQUESTED reschedule cycle; → CANCELLED from REQUESTED/CONFIRMED.
- **StorageStatement** — PROVISIONAL → VOIDED (supersede) / FINALIZED (billing run) → INVOICED (swept). Provisional accrual: whole-month convention on ACTIVE placements. Final accrual: daily proration with pinned rounding order (round daily rate first, then multiply by days).
- **CarrierInvoice** — DRAFT → SUBMITTED (sweeps APPROVED claims → SETTLED, pins claim_credit_cents) → DISPUTED / RECONCILED; RECORD_PAYMENT updates balance without changing status; DISPUTED → SUBMITTED resubmission re-sweeps.
- **OCC** — `expected_item_version` on triage (ERR_STALE_ITEM_VERSION, 412); `expected_job_version` on statement create (ERR_STALE_JOB_VERSION, 412).

### Boot verification
`bash start.sh` confirmed working on multiple ports (18899, 27731, 27745). Boots in ~1s. Binds 0.0.0.0, reads `$PORT`, runs in foreground via `exec python3 app.py`. Dependency install is guarded (`if ! python3 -c "import flask"`) so per-test reboots skip `pip install`. Fresh boots show empty state — no seeding anywhere. Logical clock defaults to exactly `2026-08-01T00:00:00Z`. End-to-end smoke test passed: auth → role check → validation → job/room/item creation → auto-advance to ACTIVE → triage (OCC-guarded) → cleaning (START → QA_PASS with fee=12000) → vault + placement → clock set.

## Step 5: Generate Unit Tests — 2026-08-14T15:58:00.000Z

All done. Final summary:

### Test counts
- **Queue A (Difficulty)**: 38 tests across 19 of 20 instances (≥2 per instance)
- **Queue B (Corner)**: 34 tests across all 34 non-stub instances (1 each)
- **Total: 72 tests**, all collected by pytest cleanly

### Skip list (1 instance)
- `Difficulty/cross_entity_state_dependency/placement_gated_on_item_triage` — **skipped, validation-priority**. The instance asserts `ERR_ITEM_NOT_SALVAGEABLE` on placement of a PENDING-triage/REGISTERED item, but PRD §3.4 applies two gates to that exact state (`condition_triage != SALVAGEABLE` → ERR_ITEM_NOT_SALVAGEABLE; `processing_status != CLEANED` → ERR_INVALID_TRANSITION) and §2.7 places both at the same priority level (seventh, "as applicable") with no intra-level tie-break. Since no reachable state isolates the salvageability gate on placement (triage NON_SALVAGEABLE always forces AWAITING_DISPOSAL), two PRD-only implementers could return either error — unique derivability fails. Not weakened, not stubbed.

The 3 `excluded_because` corner stubs were not translated; all three `difficulty_instance` cross-references resolve to real §1.8 instances (verified programmatically).

### test_helpers/ (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/test_helpers/`)
`__init__.py` (barrel), `types.py` (26 enums incl. parallel Item dimensions; CustodyEvent TypedDict omits `updated_at`/`version` per common_fields:false), `api_client.py` (44 endpoint methods incl. `/_clock/set_current_utc`), `api_errors.py` (all 28 ids, registered with `set_error_http_status_map`), `assertions.py` (per-entity + vault/invoice invariant checkers), `factories.py` (input-fields-only, unique claim/barcode/vault-code generation), `constants.py` (fee tiers, ACV/RCV constants, thresholds, default clock), `test_users.py` (opaque-role constants + per-instance builders incl. `make_subcontractor_contact_headers(sub["id"])` for the entity-backed role), `fixtures.py` (composite chains: cleaned-item, item-in-storage, finalized-statement, draft/submitted invoice, approved claim, packback-ready, dispatched referral, disposal pipeline).

### test_suite/ (9 files, same parent dir)
`conftest.py` + `test_01_jobs_rooms_items.py` (9), `test_02_triage_cleaning_disposal.py` (13), `test_03_vaults_and_placement.py` (9), `test_04_specialty_referrals.py` (6), `test_05_handling_claims.py` (6), `test_06_packback_schedules.py` (10), `test_07_statements_and_billing.py` (9), `test_08_carrier_invoices.py` (10).

### Audit results
- **Stage 1**: package imports cleanly; OCC-guarded helpers always re-capture entity/job version fresh via GET before the guarded write.
- **Stage 2 tag audit**: 72/72 tests carry exactly one `Design:` line as the final docstring line; all tags resolve to real yaml instances; queue A 19/19 covered instances have ≥2 tests, queue B 34/34 non-stub instances have ≥1.
- **PRD-citation audit**: all 72 docstrings contain a ≥8-word verbatim substring that grep-matches `workspace/PRD.md`; all 27 asserted `ApiErrorId` values are named in PRD prose (the single unused id, `ERR_ITEM_NOT_SALVAGEABLE`, is exactly the skipped instance's error).
- **No** `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold/section-table references in comments or docstrings; no freelance (design-index-external) tests.

## Step 7: Test/Fix Iteration Loop — 2026-08-14T16:10:00.000Z

Clean 8-round sweep: all 8 rounds passed 72/72. Exiting with the summary.

### Summary

**Iterations run:** 2 (iteration 1: two deterministic failures reproduced in all 8 rounds; iteration 2: clean 8/8 × 72/72 sweep).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/test_suite/test_02_triage_cleaning_disposal.py` — `TestRetriageLoop::test_retriage_salvageable_voids_pending_disposal_record` (STEP 1b/1c, unique-derivability collapse on the observation path). The PRD-verbatim rule ("its disposal record, if still `DRAFT` or `DOCUMENTED`... is automatically voided", §3.2) stays covered, but the test observed the void by asserting the fetch endpoint returns the VOIDED record — PRD pins the fetch only as "an array of zero or one entries" and pins auto-create to "if no non-voided one exists", so a faithful implementer may exclude voided records from the fetch (the implementation does). Rewrote the assertion tail to observe the void through PRD-pinned behavior: re-triage SALVAGEABLE then NON_SALVAGEABLE, then assert the fetch returns exactly one DRAFT record whose `id` differs from the first record's (a fresh auto-created record exists only if the prior one was voided). An implementation missing the void still fails this test via the `id !=` assertion.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/test_suite/test_04_specialty_referrals.py` — `TestCustodyChain::test_custody_event_immutable_no_version_field` (STEP 1b, serialization not uniquely derivable). The assertion `ev["event_at"] == "2026-08-05T10:00:00Z"` pinned the exact string echo of a client-supplied timestamp; PRD §3.3 requires only that the event carry "an `event_at` timestamp" whose instant drives the strictly-increasing ordering rule (the implementation normalizes to the platform's three-fractional-digit ISO 8601 style, a PRD-consistent choice). Relaxed to instant-equality via `datetime.fromisoformat` comparison; all other assertions (sequence, referral binding, no `version`/`updated_at`, actor) unchanged.

**Fixes applied to `implementation/`:** None — the implementation was PRD-faithful on both failure points; both were test-side over-specifications.

**Feedback notes (no deletions, but two near-miss patterns worth reporting):**
- test_02 void-observation: unit-test-generator should not observe a status flip through a read endpoint whose filter semantics PRD leaves unspecified ("zero or one entries" + non-voided auto-create condition does not determine whether VOIDED records are returned).
- test_04 event_at: unit-test-generator should not assert exact string equality on client-supplied timestamps when PRD names only the field and its semantic (ordering) role; instant comparison is the derivable assertion.

Orchestrator verification: all 8 `results.{1..8}.json` files on disk show passed=72, total=72, failed=0.

## Step 8: Finalize PRD — 2026-08-14T16:18:00.000Z

PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/workspace/PRD_FINALIZED.md`. All edits trace to the two Step 7 items; nothing else was touched.

**Size delta:** PRD.md 292 lines / 53,659 chars; PRD_FINALIZED.md 292 lines / 54,148 chars — 0% line delta (all edits inline), +489 chars ≈ +0.91% character delta. Exactly 3 lines changed.

**Changes (one bullet each):**
- §3.2 (disposal pipeline, final sentence) — revise — "array of zero or one entries" now pinned to exclude voided records: the fetch returns the item's current non-voided record when one exists, empty array otherwise — `implementation/routes/disposal.py:39-42` (the `status != "VOIDED"` filter on `GET /api/items/{id}/disposal-record`).
- §4 endpoint table, `GET /api/items/{id}/disposal-record` row — revise — description updated to "(array of 0–1, non-voided only)" to keep the table consistent with the §3.2 pin — `implementation/routes/disposal.py:35-45` (same single endpoint, same code path).
- §3.3 (custody-event paragraph) — insert + revise — added sentence pinning that supplied `event_at` is interpreted as an instant, converted to UTC, and stored/returned in the platform's normalized three-fractional-digit UTC ISO 8601 format rather than echoed verbatim (`2026-08-05T10:00:00Z` → `2026-08-05T10:00:00.000Z`); the strictly-greater ordering clause now says "compared as instants rather than strings" — `implementation/routes/referrals.py:218-243` (`parse_iso8601` + `format_iso(event_at_dt)` + instant comparison), `implementation/helpers.py:128-141`, `implementation/db.py:43-48`.

**Per-edit pre-edit search log:**

Edit 1 (§3.2 fetch sentence + §4 table row, same subject committed as one logical change):
- (a) Subject: filter semantics of the per-item disposal-record fetch — whether VOIDED records appear in the array.
- (b) Paths enumerated: `routes/disposal.py:35-45` (the fetch itself — the only list/read path for disposal records); `routes/disposal.py:48-114` (transition endpoint, addresses records directly by `id` via `get_disposal_record`, so a VOIDED record is still *addressable* and fails on state grounds); `services/cascade.py:48-66` (`ensure_disposal_record` — auto-create guarded on no non-VOIDED record, guaranteeing at most one non-voided record per item ever exists, so "zero or one" holds universally); `services/cascade.py:69-76` (`void_open_disposal_record` — voids only DRAFT/DOCUMENTED, so VERIFIED records are never voided and remain fetchable); `routes/items.py:150-163` (both triage callsites). Grep over all of `implementation/` for `disposal_record|disposal-record|VOIDED` confirmed no other paths.
- (c) Wording adjustment: scoped the exclusion explicitly to the fetch ("never appears in it") rather than claiming voided records are unreachable, because the transition endpoint can still address a VOIDED record by id (→ `ERR_INVALID_TRANSITION`); used "current non-voided record when one exists" to stay true of the VERIFIED-remains-fetchable path.

Edit 2 (§3.3 event_at sentence):
- (a) Subject: serialization and comparison semantics of the client-supplied `event_at` on custody events.
- (b) Paths enumerated: `routes/referrals.py:213-249` (create: required-check, `parse_iso8601`, ordering loop comparing the new parsed instant against re-parsed stored priors, storage via `format_iso`); `routes/referrals.py:252-260` (list: echoes stored normalized strings, sequence-ordered); `helpers.py:128-141` (`parse_iso8601`, shared with `routes/clock.py:13-23` for `to_iso8601` — wording scoped to custody events so it makes no claim about the clock endpoint); `db.py:43-48` (`format_iso`, also used for `created_at`/`updated_at`/`documented_at`, matching §2.4's existing "three fractional digits" platform format). Grep for `event_at` across `implementation/` confirmed no other paths.
- (c) Wording adjustment: phrased the ordering pin as "compared as instants rather than strings" without specifying which representation feeds the comparison, because the implementation compares the new event's full-precision parsed instant against stored millisecond-truncated instants — a sub-millisecond detail beyond the diff item's scope; deliberately did not pin truncation-vs-rounding of sub-millisecond input, and did not add a validation clause for missing/unparseable `event_at` (already derivable from §2.7 priority 4), keeping the edit strictly within the Step 7 item's revealed silence.

No other Step 7 items required PRD edits: both fixes were test-side over-specifications, the implementation was PRD-faithful, and the two pins above close exactly the two PRD silences the test rewrites worked around.

## Step 9: Complete PRD — 2026-08-14T16:40:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1760_contents_pack_out_restoration_storage/workspace/PRD_COMPLETED.md` as a minimal patch over `PRD_FINALIZED.md`, pinning every place where the prose admitted multiple readings or contradicted `implementation/`.

**Size delta**
- Source: `PRD_FINALIZED.md` — 292 lines, 54,148 chars. Result: `PRD_COMPLETED.md` — 294 lines, 58,914 chars (+2 lines, +4,766 chars). 21 inline edits; no new sections.

**Counts**: 14 ambiguity-pins, 7 mismatch-revisions.

**Change log** (all impl paths under `workspace/implementation/`):

- §2.3 — revise — mismatch — PRD claimed all list endpoints take `limit`/`offset` and carry pagination meta; pinned that only four endpoints paginate (rooms, items, referrals, statements), that other array endpoints return full arrays with no pagination meta, plus `ERR_VALIDATION` on bad limit/offset and `id` tie-break — `middleware.py:35-65`, `routes/disposal.py:35-45`, `routes/billing.py:242-248`, etc.
- §2.7 — insert — ambiguity — priority-4 schema entry now includes empty required strings — `helpers.py:55-59`.
- §2.7 — revise — mismatch — appended four endpoint-level refinements to the "fixed order": triage checks terminal-lockdown before `expected_item_version` (`routes/items.py:135-145`); statement creation checks period-validity and all supersedes checks before `expected_job_version` (`routes/billing.py:74-94`); pack-back confirm runs the structure gate before crew-window overlap (`routes/schedules.py:118-135`); on shared transition endpoints/custody creation/referral reads, action-schema and existence precede SoD/ownership/per-action-role, and on disposal/schedule/invoice transitions state-legality precedes action-payload validation (`routes/referrals.py:123-142`, `routes/claims.py:146-153`, `routes/disposal.py:50-103`, `routes/billing.py:258-318`).
- §2.8 — revise — mismatch — claim-credit invariant: swept claims can never be voided and negative `balance_cents` arises only via resubmission credit accumulation (not "post-submission claim void", which impl makes impossible); also pinned that derived-rollup recomputes never bump the owner's `version` (vault/subcontractor/statement/job) while room version does bump on child mutations — `routes/claims.py:184-190`, `routes/billing.py:276-297`, `services/recompute.py:32-48,111-128`, `routes/items.py:99-100`.
- §3.1 — revise — mismatch — `claim_number` uniqueness is not enforced (was "unique across all jobs") — `routes/jobs.py:36-55`.
- §3.2 — insert — ambiguity — SALVAGEABLE re-triage of an `IN_STORAGE` item moves it to `AWAITING_CLEANING` without releasing its active placement — `routes/items.py:150-158`.
- §3.3 — insert — ambiguity — vendor `specialty_types` must be a non-empty list of the five types else `ERR_VALIDATION` — `routes/subcontractors.py:38-43`.
- §3.3 — insert — ambiguity — referral specialty type not offered by vendor → `ERR_VALIDATION` — `routes/referrals.py:80-81`.
- §3.3 — insert — ambiguity — `SubcontractorContact` referral listing is implicitly scoped to its own vendor — `routes/referrals.py:104-105`.
- §3.3 — insert — ambiguity — `qa_note` supplied on `START`/`REWORK` is also stored on the task — `routes/cleaning.py:94-95,126-127`.
- §3.4 — insert — ambiguity — duplicate vault `code` rejected with `ERR_VALIDATION` — `routes/vaults.py:36-38`.
- §3.4 — revise — mismatch — placement gate order pinned as terminal → salvageable → `CLEANED` (PRD listed salvageability before terminal) — `routes/placements.py:63-69`.
- §3.6 — insert — ambiguity — filing on a terminal item → `ERR_ITEM_TERMINAL`; second concurrent open claim → `ERR_INVALID_TRANSITION` — `routes/claims.py:82-87`.
- §3.6 — revise — mismatch — `review_note` is accepted but never persisted on the claim (PRD said "carries") — `routes/claims.py:142-191` (no review_note handling).
- §3.6 — insert — ambiguity — a voided claim retains its computed `settlement_variant`/`settlement_amount_cents` — `routes/claims.py:184-190`.
- §3.7 — insert — ambiguity — supersedes target must exist (`ERR_NOT_FOUND`), belong to the same job, and be currently `PROVISIONAL` (`ERR_VALIDATION`) — `routes/billing.py:80-90`.
- §3.7 — insert — ambiguity — billing-run `finalized_statement_ids` sorted in ascending lexicographic order — `routes/billing.py:176`.
- §3.8 — insert — ambiguity — resubmission retains the recorded `dispute_reason` — `routes/billing.py:276-297`.
- §3.8 — insert — ambiguity — `RECONCILE` permitted only from `SUBMITTED`; a `DISPUTED` invoice must be resubmitted first — `routes/billing.py:324-328`.
- §3.9 — revise — mismatch — replaced the blanket "all further mutations rejected": closed-job rejects with `ERR_INVALID_TRANSITION` are enumerated (job transitions, room/item registration, schedule requests, invoice creation), item-scoped mutations fail via `ERR_ITEM_TERMINAL`, and statement creation / custody-event appends are not gated on closure — `routes/jobs.py:74-94`, `routes/billing.py:61-131` (no closed check), `routes/referrals.py:213-249`.
- §4 — insert — ambiguity — per-action role splits on shared transition endpoints yield `ERR_FORBIDDEN_ROLE`; unmounted path/unsupported method → `ERR_NOT_FOUND`; body not parsing to a JSON object → `ERR_VALIDATION` — `routes/disposal.py:56-59,92-95`, `routes/referrals.py:132-142`, `routes/billing.py:266-274`, `app.py:47-65`, `helpers.py:34-41`.

Everything else in the implementation (accrual formulas and rounding order, fee tiers, settlement variants, state machines, OCC semantics, custody sequencing, role tables, error catalog, response envelopes, logical clock) matched the finalized PRD as written and was left untouched.
