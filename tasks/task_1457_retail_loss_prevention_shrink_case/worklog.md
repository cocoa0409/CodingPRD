# Worklog — task_1457_retail_loss_prevention_shrink_case

## Step 1: Create Task Directory — 2026-08-13T09:08:00.000Z

Task directory `tasks/task_1457_retail_loss_prevention_shrink_case/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per orchestrator instructions; no index scan performed, no other task_* directory touched. Difficulty target: harder than expert level (per user args).

## Step 2: Generate Scaffold — 2026-08-13T10:45:00.000Z

All three scaffold artifacts are complete and lint-clean.

## Deliverables (all in `/home/ubuntu/github/CodingPRD/tasks/task_1457_retail_loss_prevention_shrink_case/`)

- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

## Counts

- **Entities: 14** (Store, Employee, PosExceptionEvent, Alert, Case, Interview, EvidenceItem, CustodyEvent [append-only, `common_fields: false`], CivilDemand, RestitutionPayment, OrcGroup, CaseLink, ShrinkPeriod, ReferralPacket)
- **State machines: 12** (58 declared transitions; cyclic on ReferralPacket `DRAFT→SEALED→SUBMITTED→RETURNED→DRAFT` and on Case `ADJUDICATING→CLOSED_SUBSTANTIATED→INVESTIGATING` via reopen)
- **Calculations: 9** (weighted alert scoring with band multipliers, tiered statutory civil demand, restitution waterfall, case loss aggregation, ORC 3-input conjunctive escalation, dual-basis shrink accrual, inventory variance with pinned feedback order, evidence retention, interview doc SLA)
- **Endpoints: 79** (incl. `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z` and `POST /ops/retention-sweep` two-phase sweeper)
- **Errors: 45**, all referenced by at least one validation/transition; **Roles: 6** (LPAnalyst, LPManager, HRPartner, LPAdmin, Auditor, PosFeed — all `opaque` identity)
- **Difficulty instances: 20** (≥2 per each of the 9 rules; combinatorial_formula has 3, one per mode a/b/c; boundary_precision_check has 3)
- **Corner instances: 87** (83 active + 4 `excluded_because` stubs), spanning all 9 guide sections: entities 12, state_machines 17, calculations 8, validations 14, errors 14, endpoints 8, rbac 7, cross_cutting layers 6, consistency_model 1
- **Lint: `VERDICT: clean lint`** — 1031 §1.8/§1.9 calls validated against §1.5; all 20 FKs reverse-reachable

## Notable design decisions

- **Archetype blend**: compliance/audit primary (segregation of duties × 3: creator≠adjudicator, interviewer≠adjudicator, demand drafter≠issuer; chain-of-custody append-only log; legal hold; retention sweeps) + ledger-reconciliation secondary (dual accrual bases, book-vs-counted variance).
- **Priority-ordered validation stack (12 rows)** with two exercised conflict pairs: state-before-fiscal (`ERR_DEMAND_NOT_PAYABLE` beats `ERR_PAYMENT_EXCEEDS_OUTSTANDING`) and safety-before-temporal (SoD beats stale-doc), plus state-before-OCC (409 beats 412).
- **OCC on two parents** (Case for demand supersede-create, ShrinkPeriod for count/recount) — the only sanctioned race semantics; stale-version tests use `${var}` captures throughout (412), satisfying lint rule (e).
- **Hard arithmetic pins**: alert weights/bands give exact 75.00 vs 74.00 escalation tests; tier2 round-then-multiply-then-round pins a 1-cent divergence (41334 vs 41333); waterfall order (fees→penalty→merch) observable per payment; NSF return adds 2500 and flips `PAID_IN_FULL→PARTIALLY_PAID→ISSUED`.
- **Two interval semantics for Rule 8**: half-open interview windows per employee (adjacency allowed) vs strictly-disjoint closed shrink periods per store (touching conflicts).
- **Cascade chains**: payment return → demand counters → demand status → case restitution_status → store rollup (depth 4); link confirm → group counters → group escalation flip → case priority recompute (depth 3); adjudication → period accrual → store total (depth 3) with full reversal on reopen.
- **Boundary sweep**: variance breach at exactly `|−0.0200|`; 72h doc SLA strict-greater (exactly 72h not stale); 30d reopen and 60d issue windows inclusive at boundary, closed +1s; retention expiry strict-greater with two-phase purge; 50000 write-off cap inclusive.
- **Instance-13 note**: `rbac_adjudicate_subject_type_routing` exercises both directions of the employee/external adjudication routing (LPManager blocked on EMPLOYEE cases, HRPartner on EXTERNAL).

Orchestrator note: the Step 2 subagent's first run ended before SCAFFOLD_CORNER_DESIGN.yaml was written; it was resumed via SendMessage and completed all three files (verified: all parse as YAML, correct top-level keys, 2134/1827/4257 lines).

## Step 3: Copy INSTRUCTION.md — 2026-08-13T10:46:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1457_retail_loss_prevention_shrink_case/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T11:20:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1457_retail_loss_prevention_shrink_case/workspace/PRD.md` (372 lines). The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.

## Section list
- §1 Introduction (2 paragraphs, pain-point + system-goal angle)
- §2 Global Specifications: 2.1 RBAC (6 roles, all `identity: opaque`, individually named) · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, 4 meta fields) · 2.4 Common Resource Properties (incl. CustodyEvent `id`+`created_at`-only exception) · 2.5 Logical Clock (startup default 2026-08-01T00:00:00Z, `to_iso8601`/`current_utc`, all clock-stamped fields) · 2.6 Money/Precision/Rounding · 2.7 Validation Order (12 priorities, numbered, first-match-wins, left-to-right nested resolution) · 2.8 OCC (exactly 2 rules) · 2.9 Segregation of Duties · 2.10 Loss Ledger rollups
- §3 Business Logic (9 subsections, timeline-grouped): 3.1 Store/Employee registry · 3.2 Exception intake & alert aggregation · 3.3 Case intake/assignment/advancement · 3.4 Interviews & doc SLA · 3.5 Adjudication/closure/reopen/merge · 3.6 Civil demands & restitution · 3.7 Evidence custody/retention/referral packets · 3.8 ORC groups & linkage · 3.9 Shrink periods & reconciliation
- §4 Endpoint Definitions — 79/79 endpoints, 4 columns only
- §5 Error Code Catalogue — 45/45 errors, 2 columns only, no trigger column

## Coverage confirmation (mechanical verification, fences stripped before tokenizing)
- **Contract 1 Field-Name Coverage:** entities[].fields 95/95, request-body ids 53/53, query params 25/25, path params 14/14, computed-read output names 8/8 — 0 missing. PASS
- **Contract 2 Rule Coverage:** all 12 validation priorities expressed as an ordered pipeline; both OCC rules named with write endpoint + `expected_case_version`/`expected_shrink_period_version` + error id + HTTP 412; all state transitions (43 distinct state values verified present) with preconditions/side effects; all 9 calculations in precise reconstruction-safe prose; all 45 error ids appear in §2/§3 prose near their triggers and in §5; cross-entity cascades (adjudication posting, reopen reversal, payment post/return 4-link cascade, merge conservation, group escalation/de-escalation priority recompute, packet legal-hold set/clear) fully stated; sibling branches given equal density (ESCALATED vs OPEN convert, recount, UNSUBSTANTIATED reopen, ISSUED↔PARTIALLY_PAID↔PAID_IN_FULL flips, acknowledge ACKNOWLEDGED vs RETURNED, NO_SHOW vs HELD). PASS
- **Contract 3 §3 Path Purity:** 688 backticked tokens scanned — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS
- Fuzzy-word scan (approximately/about/roughly/…) and pseudocode-operator scan (`==`, `>=`, `min(`, `round_half_up(`, …) both clean.

## Zero-Silence notes (rules I had to make explicit that a scaffold skim would drop)
1. **NO_SHOW outcome stamps nothing** — scaffold's empty side_effects rendered as "moves it straight to `NO_SHOW`, a terminal state, with no conduct timestamp stamped".
2. **Alert dismissal role split** — wrote "an `OPEN` alert may be dismissed by an `LPAnalyst` or an `LPManager`; an `ESCALATED` alert only by an `LPManager`" so both dismiss transitions are role-determined.
3. **`loss_posted_cents` initial value** — added "which every case carries at zero until this moment" since the field's 0-default was only implied by the reopen-reversal rule.
4. **Auto-case `manual_loss_cents`** — rewritten as "the negation of `variance_cents` when the variance is negative and to zero otherwise" to losslessly encode `max(0, -variance_cents)`.
5. **Evidence-expiry case-state set** — the state machine says "terminal or CLOSED_*" while the calculation enumerates exactly `CLOSED_SUBSTANTIATED`/`CLOSED_UNSUBSTANTIATED`/`CLOSED_REFERRED`; I used the calculation's explicit enumeration (MERGED is moot since merge re-parents all evidence to the surviving target).
6. **Case assign explicitly exempt from SoD** — stated as a deliberate non-rule ("the assignee need not differ from the case's creator") so implementers don't invent a check.
7. **Boundary inclusivity made explicit everywhere**: score exactly 75.00 escalates, exactly 72:00:00 is not stale, exact `retention_until` instant is retained, reopen allowed "on or before `closed_at` plus 30 days", write-off cap "at most 50000 cents", ORC thresholds "each boundary inclusive", interview-window adjacency allowed, period endpoints touching = conflict.

## Step 5: Generate Unit Tests — 2026-08-13T12:36:54.000Z (recovered)

RESUME NOTE: The previous run was terminated after this step's subagent finished writing files but before the orchestrator recorded its summary; the subagent's verbatim summary is lost. Artifacts recovered from disk and verified complete on resume: `test_helpers/` (9 files: `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`) and `test_suite/` (`conftest.py` + 11 test files: access_control_and_envelope, registry, alert_aggregation, case_pipeline, interviews, civil_demands, restitution_payments, adjudication_and_reopen, evidence_and_packets, orc_groups, shrink_periods). All 21 files pass `py_compile`; 122 test functions, 122 `Design: Difficulty/...` or `Design: Corner/...` docstring tags (1:1). No truncation detected; reused as-is.

## Step 6: Generate Implementation — 2026-08-13T12:36:54.000Z (recovered)

RESUME NOTE: Same termination — subagent summary lost, artifacts recovered from disk and verified complete on resume: `workspace/implementation/` with `start.sh` (PORT-aware foreground launcher, conditional pip install), `requirements.txt` (flask), `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `services/` (entities, calculations, validate), `routes/` (stores, employees, events, alerts, cases, interviews, demands, payments, evidence, referral_packets, orc, shrink_periods, ops). All 24 Python files pass `py_compile`; boot smoke test passed (server binds, `GET /stores` returns the standard array envelope with 4 meta fields). No truncation detected; reused as-is.

## Step 7: Run Tests and Iterate — 2026-08-13T12:53:00.000Z

All 8 parallel rounds are fully green: 122/122 passed in every round. Exiting with the summary.

---

## Summary

**Iterations run:** 2 sweeps (the first sweep's launch failed once on a malformed `--start-command` of my own making — missing `cd` prefix; corrected and reran before any diagnosis).

**Sweep 1 result:** 120/122 in all 8 rounds; union of failures = 2 tests, both deterministic (failed in all 8 rounds, zero flakiness observed).

**Sweep 2 result (after fixes):** 122/122 in all 8 rounds — clean exit.

### Tests deleted
None.

### Fixes applied to `test_helpers/`
None — fixtures/factories/role-header builders were all PRD-faithful.

### Fixes applied to `test_suite/`

1. `/home/ubuntu/github/CodingPRD/tasks/task_1457_retail_loss_prevention_shrink_case/test_suite/test_09_evidence_and_packets.py` — `TestCloseReferred::test_close_referred_rejected_while_packet_submitted`: added the missing `get_case` symbol to the `test_helpers` import list. Plain `NameError` test bug; the helper already existed and was barrel-exported from `test_helpers.fixtures`.

2. `/home/ubuntu/github/CodingPRD/tasks/task_1457_retail_loss_prevention_shrink_case/test_suite/test_06_civil_demands.py` — `TestIssuanceGates::test_demand_issue_window_closes_60_days_after_adjudication`: rewrote the setup to reach the 60-day issuance window the only way PRD §3.6 admits. The original test issued a DRAFT demand against a `CLOSED_SUBSTANTIATED` case, contradicting the verbatim PRD state gate it quotes ("Only a `DRAFT` demand can be issued, and only while its case is `INTERVIEWED` or `ADJUDICATING`; moreover, once the case carries an `adjudicated_at`, issuance must happen no later than sixty days after that instant"). The fixed test adjudicates at the default instant, reopens (§3.5 clears `closed_at` and cancels DRAFT demands; `adjudicated_at` persists per PRD's exhaustive reopen mutation list), walks the case back through advance → new interview → document → ADJUDICATING, drafts a fresh demand, then asserts issuance at exactly +60d succeeds and at +60d+1s fails with `ERR_DEMAND_WINDOW_CLOSED`. Boundary assertions unchanged. Also added `advance_case`, `document_interview`, `hold_interview` to the file's imports.

### Fixes applied to `implementation/`
None — the implementation was PRD-faithful on both tripped rules (the issuance state gate and the close-referred packet gate); both failures were test-side.

### Feedback notes for generators
- unit-test-generator: the 60-day window test (design tag `Corner/validations/demand_issue_window_closes_60_days_after_adjudication`) was generated with a setup that violates the state gate in the very PRD sentence it quotes — the "adjudicated_at persists + reopened case returns to ADJUDICATING" reachability analysis was missed. Temporal-window corner tests should verify the target error is reachable through PRD-legal state paths before asserting boundaries.
- unit-test-generator: `test_close_referred_rejected_while_packet_submitted` referenced `get_case` without importing it — an import-hygiene slip in generated test files.

## Step 8: Finalize PRD — 2026-08-13T13:05:00.000Z

Done. One edit was made; everything else in the Step 7 diff was either a pure test bug or already uniquely pinned by the PRD.

**Line counts / delta:** PRD.md 372 lines; PRD_FINALIZED.md 372 lines; 0% line delta (single sentence inserted inline into the existing §3.5 paragraph on line 186).

**Changes:**
- §3.5 (Adjudication, Closure, Reopening, and Merging) — insert — added the sentence "Reopen does not disturb the adjudication stamps: `adjudicated_at` and `adjudicated_by` are preserved, not cleared, so a case walked back to `INTERVIEWED` or `ADJUDICATING` still carries its adjudication instant for the sixty-day issuance window of §3.6." — `implementation/routes/cases.py:374-417` (reopen clears only `closed_at` at line 413 and never touches `adjudicated_at`/`adjudicated_by`); consumer at `implementation/routes/demands.py:118-121`.

**Items traced from `<step_7_diff>` with no edit:**
- `test_09_evidence_and_packets.py` import fix: pure test-side `NameError`. The gate under test (close-referred requires an `ACKNOWLEDGED` packet, else `ERR_CASE_NOT_REFERRABLE`) is verbatim in PRD §3.5 and matches `implementation/routes/cases.py:511-515`.
- `test_06_civil_demands.py` rewrite: the issuance state gate ("Only a `DRAFT` demand ... only while its case is `INTERVIEWED` or `ADJUDICATING`") and the inclusive 60-day boundary ("no later than sixty days after that instant", second precision per §2.6) are verbatim in PRD §3.6 and match `demands.py:107-121`. The reopen side effects the rewrite relied on (`closed_at` cleared, DRAFT demands cancelled, INTERVIEWED/ADJUDICATING walk-back, fresh draft) were already explicit in §3.3-§3.6. Only `adjudicated_at` persistence was silent — hence the one edit.

**Pre-edit search log (edit 1):**
- (a) Subject: the mutation set of case reopen, specifically the lifecycle of `adjudicated_at`/`adjudicated_by` and their downstream consumer, the 60-day demand-issuance window.
- (b) Paths enumerated and read/grepped: `grep -rn "adjudicated_at|adjudicated_by"` across all of `implementation/` — hits: `services/entities.py:114-115` (initialized `None` at case creation), `routes/cases.py:341-342` and `:364-365` (stamped at every adjudication, both SUBSTANTIATED and UNSUBSTANTIATED — so re-adjudication re-stamps), `routes/cases.py:374-417` (reopen; clears only `closed_at`, never the adjudication stamps, in both the substantiated and unsubstantiated branches), `routes/cases.py:263-277` (dismiss; stamps only `closed_at`), `routes/cases.py:420-479` (merge; never touches them), `routes/cases.py:503-519` (close-referred; never touches them), `routes/demands.py:118-121` (window check reads the case's currently carried `adjudicated_at`; boundary `now > adjudicated_at + 60d` fails, exactly +60d passes).
- (c) Wording adjustment: scoped the sentence to reopen only ("Reopen does not disturb ... preserved, not cleared") rather than any universal claim about the window running "from the original adjudication", because re-adjudication (`cases.py:341,364`) re-stamps `adjudicated_at` and the window then measures from the new instant. The sentence is also placed before the unsubstantiated-reopen sentence so it covers both reopen branches, matching the shared reopen code path.

## Step 9: Complete PRD — 2026-08-13T13:33:00.000Z

The completed PRD is written. Final verification of the change set is consistent — 33 edited loci, all inside `workspace/PRD_COMPLETED.md`; no other file was touched, and SCAFFOLD*.yaml / worklog.md were never read.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (372 lines / 61,772 chars) → `PRD_COMPLETED.md` (376 lines / 66,397 chars); char-delta **+4,600**.

**Counts:** 29 ambiguity-pins, 4 mismatch-revisions (33 changes total).

**Changes (one per bullet):**

- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, never wall-clock — response.py:19, db.py:42-48
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` 404; unsupported method or malformed/non-object JSON body → `ERR_INVALID_REQUEST` 400 — app.py:43-55, services/validate.py:9-16
- §2.3 — insert — ambiguity — list sort ties broken by `id` ascending; `has_more` true exactly when `offset`+`limit` < `total_count` — response.py:37, routes/stores.py:39
- §2.4 — insert — ambiguity — resources born at `version` 1; alerts and cases are created at `version` 2 (creation-time derivation counts as mutation), events aggregated at intake at `version` 2 — services/entities.py:17-23, routes/cases.py:122-127, routes/events.py:77-102
- §2.7 — insert — mismatch — pinned pipeline order not literally followed; effective order pinned: headers → endpoint role → body well-formedness → anchor existence → ownership → remaining body FKs → steps 6–12; adjudication subject-type routing evaluated after case resolution, immediately before the state check — routes/demands.py:31-55, routes/interviews.py:28-46, routes/cases.py:285-307
- §3.2 — insert — ambiguity — alert candidate window inclusive at both ends — routes/events.py:91-92
- §3.2 — insert — ambiguity — `LPAnalyst` dismissing an `ESCALATED` alert fails with `ERR_FORBIDDEN_FOR_ROLE` — routes/alerts.py:70-73
- §3.2 — insert — ambiguity — convert with `EXTERNAL`/`UNKNOWN` requires null payload `employee_id` (`ERR_SUBJECT_MISMATCH`); bundled-alert violations (wrong state/store) fail with `ERR_INVALID_STATE_TRANSITION` — routes/alerts.py:128-140
- §3.2 — revise — ambiguity — converted case is HIGH when the primary **or any bundled** alert is `ESCALATED`; non-numeric `min_score` fails with `ERR_INVALID_REQUEST` — routes/alerts.py:142-143,159,42-46
- §3.3 — insert — ambiguity — `manual_loss_cents` defaults 0, negative → `ERR_INVALID_REQUEST`; `case_number` exact format `LP-<store_number>-NNNNNN` (6 digits from 000001); auto-case excepted from caller-`created_by` rule — routes/cases.py:113, services/entities.py:89-93
- §3.3 — insert — ambiguity — summary `demand_outstanding_cents` sums only `ISSUED`/`PARTIALLY_PAID` demands — routes/cases.py:172-173
- §3.4 — revise — mismatch — "same consistency rules as case creation" replaced: `subject_employee_id` allowed on any subject type; TERMINATED → `ERR_EMPLOYEE_NOT_ACTIVE`; on `EMPLOYEE`-subject cases must equal case's `employee_id` — routes/interviews.py:52-59
- §3.4 — insert — ambiguity — overlap applies whenever `subject_employee_id` present across all cases, and subject consistency is evaluated before the overlap check — routes/interviews.py:57-76
- §3.4 — insert — ambiguity — any `LPAnalyst` may cancel a `SCHEDULED` interview (no assignee/interviewer restriction) — routes/interviews.py:165-175
- §3.5 — insert — ambiguity — `INTERVIEWED`→`ADJUDICATING` advance also accepts `recovered_value_cents` under the same cap — routes/cases.py:243-254
- §3.5 — insert — ambiguity — "latest `DOCUMENTED` interview" means latest by `documented_at` — routes/cases.py:322
- §3.5 — insert — ambiguity — `employment_action` optional, validated only when present; omitted → employee status unchanged, count still increments — routes/cases.py:286-289,345-351
- §3.5 — insert — ambiguity — unsubstantiated adjudication leaves `restitution_status` unchanged — routes/cases.py:362-371
- §3.5 — insert — ambiguity — reopen request carries a `reason`; reopen clears `loss_posted_period_id` along with `loss_posted_cents` — routes/cases.py:379,93-94
- §3.5 — revise — mismatch — missing merge target fails with `ERR_NOT_FOUND` (not `ERR_MERGE_NOT_ALLOWED`); target refused when in any closed state or `MERGED` — routes/cases.py:428-438
- §3.6 — insert — ambiguity — `priors_offense_count`/`recovery_cost_cents` must be non-negative when supplied — routes/demands.py:35-36
- §3.6 — insert — ambiguity — issuance flips `restitution_status` to `OUTSTANDING` only when the issued demand's outstanding is positive; zero-balance issuance reads `SETTLED` — routes/demands.py:139-142
- §3.6 — insert — ambiguity — payment recording gated only on demand existence, not status; payability enforced at posting — routes/payments.py:26-36
- §3.7 — insert — ambiguity — no item status other than the SEALED ACCESSED/TRANSFERRED rule restricts custody appends — routes/evidence.py:163-165
- §3.7 — revise — ambiguity — any `LPAnalyst` may seal evidence (no assignee restriction) — routes/evidence.py:102-117
- §3.7 — insert — ambiguity — `CASE_HOLD` item's `retention_until` reads null while its case is not closed — services/calculations.py:251-262
- §3.7 — insert — mismatch (vs global order) — packet seal evaluates the unsealed-evidence check (`ERR_EVIDENCE_UNSEALED`) before the custody-gap check (`ERR_CUSTODY_GAP`) — routes/referral_packets.py:80-93
- §3.8 — insert — ambiguity — `link_score` outside 0–100 fails with `ERR_INVALID_REQUEST` — routes/orc.py:108-111
- §3.8 — revise — ambiguity — link confirm requires the case in a live state (`OPEN`/`INVESTIGATING`/`READY_FOR_INTERVIEW`/`INTERVIEWED`/`ADJUDICATING`); any closed state or `MERGED` fails — routes/orc.py:21-22,164-167
- §3.8 — insert — ambiguity — disrupting a group does not recompute confirmed-linked case priorities; priority changes only on link confirmation, escalation flips, and merge-driven de-escalation — routes/orc.py:63-77, services/calculations.py:174-215
- §3.9 — insert — ambiguity — `counted_inventory_cents` zero-or-more (negative → `ERR_INVALID_REQUEST`) — routes/shrink_periods.py:101
- §3.9 — insert — ambiguity — reconciling a `RECONCILED` or `CLOSED` period fails with `ERR_INVALID_STATE_TRANSITION` — routes/shrink_periods.py:130-132
- §3.9 — insert — ambiguity — shrink auto-case `created_by` is the literal string `system` and mints a `case_number` from the store sequence — routes/shrink_periods.py:144-152

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1457_retail_loss_prevention_shrink_case/workspace/PRD_COMPLETED.md`
