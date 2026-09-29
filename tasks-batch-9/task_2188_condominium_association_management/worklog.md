# Worklog — task_2188_condominium_association_management

## Step 1: Create Task Directory — 2026-08-31T17:54:21.373Z

Created `tasks/task_2188_condominium_association_management/` and `tasks/task_2188_condominium_association_management/workspace/` (pre-allocated name used verbatim; no index scan).

## Step 0: Resume-mode audit — 2026-08-31T18:06:00.000Z

Prior run crashed after Step 1. On-disk audit: only `worklog.md` and an empty `workspace/` existed. No SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, PRD.md, test_helpers/, test_suite/, or implementation/. Pipeline resumed from Step 2.

## Step 3: Copy Shared Files — 2026-08-31T18:06:30.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (53 lines). Run out of order relative to Step 2 (no dependency).

## Step 0: Resume-mode audit (second resume) — 2026-08-31T18:20:00.000Z

Prior run crashed again, this time after Step 3. On-disk audit of `tasks/task_2188_condominium_association_management/`: only `worklog.md` (13 lines) and `workspace/INSTRUCTION.md` (53 lines, verified byte-identical to project-root `INSTRUCTION.md` via `diff`) exist. Missing entirely: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone. Pipeline resumed from Step 2 in the same task directory.

## Step 0: Resume-mode audit (third resume) — 2026-08-31T18:40:00.000Z

Prior run crashed after Step 3 again. Full `find`-based audit of the task directory found exactly two files: `worklog.md` (17 lines) and `workspace/INSTRUCTION.md` (53 lines, re-verified byte-identical to project-root `INSTRUCTION.md` via `diff`). No scaffold trio, no `workspace/PRD.md`, no `test_helpers/`, no `test_suite/`, no `workspace/implementation/`, no `PRD_FINALIZED.md`, no `PRD_COMPLETED.md`. Steps 1 and 3 remain valid and were NOT redone. Pipeline resumed from Step 2 in the same task directory.

## Step 0: Resume-mode audit (third resume) — 2026-08-31T19:02:00.000Z

Prior run crashed again after Step 3. On-disk audit: `worklog.md` (17 lines) and `workspace/INSTRUCTION.md` (verified byte-identical to project-root `INSTRUCTION.md` via `diff`) are the only artifacts. Missing entirely: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone. Pipeline resumed from Step 2 in the same task directory.

## Step 0: Resume-mode audit (fourth resume) — 2026-08-31T19:30:00.000Z

Fifth attempt at this task; all four prior runs crashed inside Step 2 (scaffold generation) without writing any scaffold file. `find`-based audit of the task directory found exactly two files: `worklog.md` (25 lines) and `workspace/INSTRUCTION.md` (53 lines, re-verified byte-identical to project-root `INSTRUCTION.md` via `diff` — exit 0). Absent: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `workspace/PRD.md`, `test_helpers/`, `test_suite/`, `workspace/implementation/`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`. Steps 1 and 3 confirmed valid and NOT redone. Pipeline resumes from Step 2 in this same task directory.

## Step 0: Resume-mode audit (fifth resume, orchestrator PID 3018420) — 2026-08-31T18:49:00Z

Audited on disk: only `worklog.md` and `workspace/INSTRUCTION.md` (53 lines, byte-identical to project-root `INSTRUCTION.md` via `diff`, exit 0). Steps 1 and 3 valid, NOT redone. Everything from Step 2 onward missing.

**Root cause of the repeated crashes identified.** This task directory was being run by MULTIPLE CONCURRENT orchestrators — the supervisor invoked `launch.sh 2188 resume` repeatedly (~every 5 min). At 18:49 three live `claude -p /prd-bench-entrance` processes targeted task_2188 simultaneously (PIDs 3018420, 3023411, 3026497), plus a 4th that had just died. Each wrote its own "resume audit" worklog entry, then died inside Step 2 having persisted nothing — which is why five attempts produced zero scaffold bytes. Applied a deterministic tie-break (lowest live PID proceeds) plus an atomic lock at `/tmp/prd-bench-2188.lock`; the other orchestrators then exited on their own, leaving PID 3018420 sole survivor.

**Second root cause.** The first Step 2 attempt from this orchestrator ALSO died: "Agent stalled: no progress for 600s (stream watchdog did not recover)", having emitted only "I'll start by reading the skill specification." The scaffold-generator skill dir holds a 73KB SKILL.md beside 22 example YAMLs of 30-66KB each; bulk-reading those is the likely stall trigger. Mitigation applied for the retry: (a) split Step 2 into three smaller agents, one per output file, so SCAFFOLD.yaml persists before the design indices begin; (b) restricted reading to specific SKILL.md line ranges and hard-prohibited the `examples/` directory; (c) mandated incremental append-to-destination writes instead of compose-in-context-then-write-once.

## Step 2a: Generate SCAFFOLD.yaml — 2026-08-31T19:54:00Z

Done.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2188_condominium_association_management/SCAFFOLD.yaml` — 3843 lines, parses cleanly under `yaml.safe_load`.

**Top-level keys (13):** `api_prefix, calculations, complexity_profile, concurrency_rules, domain_name, endpoints, entities, errors, response_envelope, roles, scenario, state_machines, validations`. Neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present (both verified `False`).

**Counts:** 15 entities (41 FK fields) · 9 state machines / 76 transitions · 3 OCC concurrency rules · 12 calculations · 60 ordered validations (priorities exactly 1–60, no gaps or dupes) · 77 endpoints · 81 errors · 7 roles.

**Design highlights (difficulty pushed above Expert):**
- Ledger archetype + multi-party negotiation; graph topology, cyclic state machines, segregation-of-duties role model.
- Dual-variant calcs on disjoint domains: `payment_application_waterfall` (STATUTORY_PRIORITY vs OWNER_DIRECTED over a 6-bucket order), `reserve_adequacy` (STRAIGHT_LINE vs COMPONENT method), `resale_payoff` (LEDGER_BALANCE vs ESTIMATED_PAYOFF with actual/actual half-open proration).
- Two deliberately different remainder-rounding regimes: cyclic 1-cent drift distribution in `assessment_allocation` vs floor-then-drift in `deductible_waterfall` (which also has a pinned 5-step order resolving an apparent circular dependency).
- Two ≥4-hop cascades from different triggers (budget adoption; fine vacatur compensation), two conserved quantities (INVARIANT L on owner ledger cents, INVARIANT E/S on contract encumbrance and restricted SA cash), two temporal-overlap geometries (closed interval + 24h buffer on CommonElement vs half-open 30-min slots + docket capacity on BoardMeeting), and a contrast trap between `special_assessment_tally` (eligible weight, ≥6667bp affirmative) and `budget_ratification_tally` (total interest, ≥5000bp veto — eligibility intentionally not applied).
- All 3 OCC rules are CREATE-with-supersede on a parent `version` (Association/Unit/VendorContract), each 412 with its own `expected_*_version` input and version bump in side effects.

**Verification performed beyond the mandated parse:** every validation/concurrency `error_id` exists in the catalog and every catalog error is referenced by at least one row; all endpoint roles are declared in §1.7; all 41 FKs are reverse-reachable via a filtered-list GET returning `<Child>[]`; no duplicate endpoint keys, error ids, or entity names; logical clock endpoint `POST /_clock/set_current_utc` present with the `2026-08-01T00:00:00Z` default.

**One gotcha worth flagging for other scaffold generators:** SKILL.md's schema shows `input: [field_name, other_field?]`, but PyYAML rejects a plain scalar ending in `?` inside a flow sequence (`a: [x, y?]` → ParserError). I had to double-quote the optional-field tokens across 40 `input:` lines to make the file parse.

**Orchestrator independent re-verification:** `yaml.safe_load` OK; 13 keys; both forbidden keys absent; counts confirmed (15/9/12/60/77/81/7/3); file ends mid-structure-free on a complete endpoint line.

## Step 2b: Generate SCAFFOLD_DIFFICULTY_DESIGN.yaml — 2026-08-31T20:33:00Z

File complete and validated.

**Path:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` · **Line count:** 2211 · **Top-level keys:** exactly one — `scaffold_difficulty_design` · **Rule groups:** 9/9 · **Instances:** 18 (2 per rule, all `name:` values unique)

| rule_id | instances |
|---|---|
| `dual_variant_calc` | reserve_adequacy STRAIGHT_LINE vs COMPONENT (6976/DEFICIENT vs 7200/ADEQUATE); resale_payoff LEDGER_BALANCE vs ESTIMATED_PAYOFF (35,000 vs 713,333) |
| `combinatorial_formula` | assessment_allocation mode b — negative drift -2 on pool 900,002; deductible_waterfall mode c — tier basis pinned to gross damage (2,500,000/500,000 not 1,800,000/1,200,000) |
| `non_linear_state_machine` | Budget revision cycle DRAFT->...->REJECTED->DRAFT->...->ADOPTED; SpecialAssessment parallel dimensions (funding advances while approval frozen) |
| `transitive_cascade` | Budget adoption 5-hop -> BALLOTING `eligible_weight_bp` 4000->10000; litigation TENDERED 2-hop -> cert void + fee reversal |
| `priority_pair_validation_conflict` | state p13 beats business_fiscal p43 on `/budgets/{id}/ratify`; business_safety p16 beats business_referential p20 on `/vendor-contracts/{id}/reinstate` |
| `boundary_precision_check` | `yes_share_bp` 6666 FAILS / 6667 APPROVES, plus floor->9998 where round_half_up gives 9999; invoice ceiling `floor(1234567*11/10)==1358023` accepts, 1358024 rejects |
| `cross_entity_state_dependency` | (InsuranceClaim, SpecialAssessment) IN_LITIGATION needs an APPROVED funder on *that* claim + reverse-direction ERR_LITIGATION_ACTIVE; (MaintenanceWorkOrder, CommonElement) only DECOMMISSIONED blocks start, IMPAIRED does not |
| `resource_temporal_overlap` | CommonElement closed interval + 24h buffer — touching the buffered edge collides (1-second falsifiers both sides); BoardMeeting half-open 30-min slots — touching allowed, 20:30 is the last legal start |
| `compensating_invariant` | INVARIANT L: fine vacatur restores 13000->8000 exactly and unwinds lien/eligibility/ballot counting; INVARIANT E: hold releases nothing, invoice removes the *estimate* (900000, not 834567) |

**Automated conformance checks run (all zero problems):** every `grounds:` ref resolves to a real SCAFFOLD.yaml element; every `call:` resolves to a declared §1.5 endpoint and every `payload:` field is in that endpoint's `input:`; every `as:` is a declared role permitted on that endpoint; all three `entity_backed` roles always carry `as_user_id`; every `${var}` is bound by an earlier `captures:`; all `expected_*_version` values are `${var}` never literals; all 21 `ERR_*` ids exist in `errors:`.

**Two scaffold-fidelity bugs caught and fixed during verification:** SpecialAssessment's failing approval state is `FAILED`, not `REJECTED` (`REJECTED` belongs to Budget); `MaintenanceWorkOrder.hold_reason` has no `WEATHER` member — changed to `ELEMENT_UNAVAILABLE`.

All numeric assertions were computed by code (exact `round_half_up` via `fractions.Fraction`, `floor` arithmetic, day-count arithmetic) rather than estimated.

**Orchestrator re-verification:** parses; single top-level key; 9 groups x 2 = 18 instances; 18/18 names unique, no duplicates.

## Step 2c: Generate SCAFFOLD_CORNER_DESIGN.yaml — 2026-08-31T20:52:00Z

Done. `SCAFFOLD_CORNER_DESIGN.yaml` is complete and clean.

- **5,803 lines**, valid non-truncated YAML. **Single top-level key confirmed:** `['scaffold_corner_design']`.
- **All 9 taxonomy sections covered, 92 instances total** (all names unique globally, not just per section): entities 13, state_machines 13, calculations 10, validations 14, endpoints 7, errors 16, rbac 10, cross_cutting_complexity_layers 7, consistency_model 2.
- Every instance carries `name` / `claim_type` / `grounds` / `distinguishing_aspect` / `test_recipe{setup, setup_api_calls, trigger, assert}`; every negative trigger captures `$.data.error_id`. No `excluded_because:` stubs (the §1.8 file was deliberately not read).

**Sections added:**
- `errors` (16): one previously-untriggered error code each — ERR_ENTRY_ALREADY_REVERSED, ERR_AGENDA_KIND_MISSING, ERR_DUPLICATE_ADOPTED_BUDGET, ERR_BALLOT_ALREADY_OPEN, ERR_NO_ELIGIBLE_VOTERS, ERR_NO_AFFECTED_UNITS, ERR_RESPONSIBILITY_MISMATCH, ERR_CLAIM_SCOPE_INVALID, ERR_INSTALLMENTS_EXHAUSTED, ERR_UNIT_DOCKET_LIMIT, ERR_CASE_ALREADY_CURED (vs generic ERR_CASE_ALREADY_TERMINAL), ERR_STALE_UNIT_VERSION, ERR_MEETING_NOT_IN_SESSION, ERR_CERT_CLOSING_DATE_PAST, ERR_CONTRACT_TERM_INVALID, ERR_APPEAL_WINDOW_CLOSED (inclusive deadline, +1s fails).
- `rbac` (10): exclusive/shared/peer denials (CM cannot ratify, director cannot reverse a ledger entry, treasurer cannot approve a contract, TitleAgent has no ledger writes, adjuster cannot open the claim, attorney-only litigation-stage plus its certificate-void cascade, owner may pay but not charge, SA authorship vs balloting split) and both limbs of segregation of duties (reporter != decider; round-1 decider disqualified in round 2).
- `cross_cutting_complexity_layers` (7): the three §1.2.1 `concurrency_rules` OCC tests (association/unit/contract, each with a stale->412 and refreshed->success pair), two cascade tests (4-hop ratification cascade including the post-adoption unit that must stay at 0; TENDERED fan-out over `affected_unit_ids` sparing the third unit), dual-variant allocator divergence (MONTHLY_OPERATING remainder 1 vs SA_INSTALLMENT remainder 0), and `ops_run_checkpoint`.
- `consistency_model` (2): `immediate` — ratify's own response carries the full `allocation_snapshot`; the payment response already carries the re-derived posture.

**Lint:** `scaffold_lint.py` reports **0 findings against §1.9** (92 instances / 1,482 calls scanned). Three payload-conformance bugs fixed: payments take `effective_period` not `received_at`; work orders take `estimated_cost_cents` not `estimate_cents`; `POST /vendor-contracts/{id}/approve` takes no body.

**Flagged upstream (unused by any assertion):** `GET /resale-certificates/{id}/lender-questionnaire` is TitleAgent-exclusive in §1.7 but its endpoint `roles:` is `[TitleAgent, CommunityManager, BoardTreasurer]`. Also reported: 4 lint violations attributed to `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and 41 pre-existing SCAFFOLD.yaml `FK_REVERSE_UNREACHABLE` findings.

**Orchestrator re-verification:** parses; single top-level key; 9 sections; 92 instances; 92/92 names unique, no duplicates.

## Step 4: Generate PRD — 2026-08-31T21:13:00Z

PRD generation is complete.

**Deliverable:** `workspace/PRD.md` — **577 lines**, built incrementally on disk in five append checkpoints (§1–2.3 -> §2.4–2.10 -> §3.1–3.3 -> §3.4–3.6 -> §3.7–3.9 -> §4–5), so no work was ever held only in context.

**Structure:** §1 Introduction (3 paragraphs) · §2 Global Specifications — 10 subsections: RBAC, verbatim Response Structure block, pagination, identity/versioning/logical clock, association scope and left-to-right path resolution, optimistic concurrency, money/basis-points/rounding, cascade discipline and the three conservation invariants (L, E, S), the 60-rung validation ladder, and by-law tunables with every default · §3 Business Logic — 9 subsections: unit ledger and delinquency ladder; budget cycle and assessment allocation; board meetings/quorum/vote register; special assessments; the billing-run checkpoint; common elements, vendor contracts, work orders and reserve adequacy; insurance claims and the deductible waterfall; rules enforcement and fine hearings; resale certificates and closing · §4 77-row endpoint table · §5 81-row error catalogue.

**Coverage confirmed:** all **15 entities**, **9 state machines / 76 transitions** (every from->to pair, both branches of every sibling pair, all 12 system-driven transitions), **12 calculations** (both variants of each of the 5 dual-variant ones), **60 validations** (priorities 1–60 enumerated in order with error_id and scope), **77 endpoints**, **81 errors**, **7 roles**.

**Hard Contract reports:**
- **Contract 1 — Field-Name Coverage: PASS.** 215 required identifiers (all `entities[].fields[].name` plus all endpoint `input` identifiers and `{path_param}` names) checked mechanically against backticked tokens; 0 missing under the strict standalone-token test.
- **Contract 2 — Rule Coverage: PASS.** All 60 validation error_ids and all 81 catalogue error_ids appear in §2/§3 prose ahead of the §5 table; all state names, all enum values across every entity field, and all 7 role names appear in prose; every transition's preconditions and side effects stated on both branches, including the deliberately asymmetric pairs (operator vs. cascade certificate void and the fee refund; round-1 vs. appeal-round meeting-cancellation de-docketing; `ADJUSTED_OWNER` settlement lacking the litigation guard and the element reset; `APPEALED -> UNDER_REVIEW` not recomputing `common_element_damage_cents`).
- **Contract 3 — §3 Path Purity: PASS.** 462 distinct backticked tokens in §3; zero begin with `/`, zero are bare HTTP methods, zero combine method with path; no unbackticked path-like text (only `/` hit is the prose phrase "actual/actual"). Paths appear only in §4.
- §2.2 matches `section-2.2-response-structure.md` byte-for-byte; no pseudocode operators and no fuzzy quantifiers anywhere.

**Two judgement calls flagged:** the scaffold never states the `bucket` for `entry_type` `RESALE_FEE`, so §3.1 pins it to `COLLECTION_COST` (mapping it to `NONE` would make the row permanently unpayable and permanently inflate `oldest_unpaid_age_days`); and the association-revision paragraph enumerates exactly the twenty-one mutable tunables plus the immutable and server-maintained fields, since an "all except" phrasing would have wrongly implied `total_interest_bp`, `reserve_designated_cents`, and `restricted_sa_cash_cents` were client-writable.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator re-verification:** 577 lines / 139,288 bytes; 5 top-level sections at expected offsets; §4 contains exactly 77 endpoint rows; §5 contains exactly 81 `ERR_` rows and 81 unique `ERR_*` tokens document-wide; file ends on a complete table row (non-truncated).

## Step 6: Generate Implementation — 2026-08-31T21:53:00Z

Implementation complete and booting cleanly.

**Module layout (`workspace/implementation/`, 4602 lines):**

| file | lines | contents |
|---|---|---|
| `start.sh` | 8 | foreground launcher, guarded pip, `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 60 | app factory, error handlers, `PORT`/`0.0.0.0` bind, `threaded=False`, `use_reloader=False` |
| `errors.py` | 109 | all 81 error ids + statuses (verified identical to SCAFFOLD, zero mismatches) |
| `clock.py` | 87 | logical clock, default `2026-08-01T00:00:00Z`, floored whole-day arithmetic |
| `db.py` | 120 | in-memory dicts for 15 collections, `touch` with per-request version-bump dedupe |
| `money.py` | 70 | `round_half_up`, `floor_div`, `cyclic_allocate`, `floor_then_topup` |
| `auth.py` / `validation.py` / `response.py` / `serialize.py` | 58/283/50/31 | roles + rungs 1–9, envelope, datetime rendering |
| `services/ledger.py` | 260 | entries, waterfall, aging, delinquency ladder, Invariant L |
| `services/alloc.py`, `assessment.py`, `certificate.py`, `contracts.py` | 45/165/140/96 | allocation pools, ballot weights + Invariant S, payoff/cascade-void, Invariant E |
| `routes/core.py` | 300 | associations, owners, units, reserve adequacy (both variants) |
| `routes/ledger_routes.py` | 170 | charges, payments, reversal, statement, transfer-ownership |
| `routes/planning.py` | 497 | budgets (propose->notice->ratify->adopt cascade) + billing runs (6-step sweep) |
| `routes/assessments.py` | 365 | special assessments + vote register |
| `routes/meetings.py` | 183 | board meetings incl. cancel de-docketing |
| `routes/elements.py` | 590 | common elements, vendor contracts, work orders |
| `routes/claims.py` | 342 | claims, 4 adjustment branches, deductible waterfall, litigation, settle |
| `routes/cases.py` | 391 | violation cases, fine tiers, dockets, vacatur cascade |
| `routes/certificates.py` | 181 | resale certificates + lender questionnaire |

**Verification:**
- **Route parity:** programmatically diffed the Flask url_map against the SCAFFOLD `endpoints` section — **77/77 exact, 0 missing, 0 extra**.
- **Error parity:** 81/81 error ids present with **identical `http_status` for every one**.
- **Boot check:** `PORT=8991 timeout 15 bash start.sh` -> clean start, no import errors, binds 0.0.0.0. Fresh-process `GET /owners` returns `total_count: 0`, confirming zero seeding. No file I/O anywhere (`grep` for `sqlite3|open(|json.dump|pickle|/tmp|shelve` returns nothing) — every byte of state dies with the process.
- **End-to-end smoke:** a 60-call script exercised assoc->owners->units->meeting->budget propose/notice/convene/veto-vote/ratify->billing run->payment->SA ballot/installment->element/contract/award/work order/invoice->SPLIT claim/settle->violation notice/docket/fine/appeal->certificate request/issue/questionnaire/transfer->reserve adequacy. All green. Negative paths confirmed live: 401/403-role/403-actor/404, both `412 ERR_STALE_ASSOCIATION_VERSION` and `412 ERR_STALE_UNIT_VERSION`, `ERR_RESERVE_CONTRIBUTION_TOO_LOW`, `ERR_INVOICE_EXCEEDS_TOLERANCE`, `ERR_INSUFFICIENT_OPERATING_CASH`, `ERR_WINDOW_NOT_STARTED`, `ERR_BOARD_QUORUM_NOT_MET`, `ERR_AGENDA_KIND_MISSING`.
- **Invariants:** a checker walked every association over the live dataset — Invariant L (ledger sum == `balance_due_cents`), Invariant E (committed/invoiced/cap), Invariant S (restricted SA cash) — **0 violations**.

**PRD ambiguities resolved with a concrete choice:**
1. **Version bumping under multi-hop cascades** — §2.8 says each touched row advances by 1; `db.touch` dedupes per request so a row reached through several hops advances exactly once.
2. **Rung 11 reachability** — `CURED` is in rung 10's terminal set, which would make `ERR_CASE_ALREADY_CURED` dead code. On `schedule-hearing` I check `CURED` first so both codes stay reachable.
3. **`send-notice` rung order** — ladder priority wins over SCAFFOLD's precondition listing order: rung 25 `ERR_NOTICE_PERIOD_NOT_SATISFIED` before rung 33 `ERR_AGENDA_KIND_MISSING`.
4. **Budget ratify** — rungs 35/43/49 enforced only on the adoption branch (per PRD prose), and the reserve minimum is re-checked there even though the ADOPTED preconditions omit it.
5. **`decision_owner_id`** — set on FINE and DISMISS only; the UPHOLD/VACATE side-effect lists deliberately omit it.
6. **Vendor-contract approve** — a qualified-YES shortfall raises `ERR_AGENDA_KIND_MISSING` (rung 14 does not list approve).
7. **SA open-ballot funding-claim precondition** — uses `ERR_INVALID_CLAIM_STATE`; rung 21 `ERR_LITIGATION_FUNDING_MISSING` is scoped to `litigation-stage` only.
8. **Work-order creation** — does not gate on contract status; PRD names exactly four business checks (mismatch/term/buffer-conflict/cap), so `is_emergency` is descriptive rather than an enforced bypass.
9. **`fiscal_year` containing `closing_date`** — computed from `fiscal_year_start_month` (year-1 when the closing month precedes the start month), not naive `.year`.
10. **Owner scoping (rung 7)** — applied to exactly three operations (fine appeal, owner ballot, unit statement) and only when the acting role is literally `UnitOwner`.
11. **Segregation rule "manager who proposed a budget may not ballot on it"** — unimplementable as specified: `Budget` records no proposer field. Documented no-op.
12. **`applied_cents` on a reversed row** is left intact; `collected_cents` derives from payments' `applied_allocations`. `restricted_sa_cash_cents` recomputed after every collection/refund so Invariant S holds exactly, while `Association.version` bumps only where the PRD literally says.
13. **`transfer_blocked`** derived inside `recompute_unit`; payments do not credit `operating_cash_cents` (§2.10 over the field note); `InsuranceClaim.reported_at` stamped despite absence from the field list (§3.7 requires it); PATCH endpoints reject any key outside their declared patchable sets with `ERR_VALIDATION`.

The two remainder regimes are kept strictly separate: `money.cyclic_allocate` (half-up per line, then cyclic 1-cent drift with wraparound) for assessment allocation, and `money.floor_then_topup` (floor, then single-pass +1c to the first *drift* participants ordered `heated_sqft` DESC / `created_at` ASC) for the deductible waterfall.

## Step 5: Generate Unit Tests — 2026-08-31T23:40:00Z

**NOTE ON EXECUTION:** this step ran in two passes. The first pass completed all of `test_helpers/`, `conftest.py`, and 100% of queue A (18/18 §1.8 instances, 113 tests), then died mid-run: "Agent terminated early due to an API error: Server error mid-response" while starting the boundary-precision file. Because the durability mandate forced incremental writes, ALL of that work survived on disk. The orchestrator audited on-disk state (confirmed 18/18 Difficulty tags present, zero Corner tags), then RESUMED the same agent with its context intact and scoped it to queue B only. No queue-A file or helper was regenerated.

All nine queue-B files are on disk and verified. Final state:

**New files (queue B, §1.9 Corner) — one per section**

| file | lines | tests |
|---|---|---|
| `test_suite/test_corner_entities.py` | 779 | 15 |
| `test_suite/test_corner_state_machines.py` | 1013 | 12 |
| `test_suite/test_corner_calculations.py` | 1048 | 10 |
| `test_suite/test_corner_validations.py` | 998 | 14 |
| `test_suite/test_corner_endpoints.py` | 699 | 6 |
| `test_suite/test_corner_errors.py` | 1001 | 14 |
| `test_suite/test_corner_rbac.py` | 852 | 10 |
| `test_suite/test_corner_cross_cutting.py` | 768 | 7 |
| `test_suite/test_corner_consistency_model.py` | 228 | 2 |

Queue B total: 7386 lines, **90 tests**. Pre-existing and untouched: `test_helpers/` (9 modules + `__init__.py`, 2940 lines), `test_suite/conftest.py` (34), and the nine queue-A files (4870 lines, 113 tests). No helper module was added or rewritten. Suite total: **203 tests**, 12290 lines under `test_suite/`.

**Instances translated vs skipped**

Queue A (§1.8 Difficulty): 18/18 translated, 0 skipped.
Queue B (§1.9 Corner): **88/92 translated, 4 skipped** — entities 13/13, state_machines 12/13, calculations 10/10, validations 14/14, endpoints 6/7, errors 14/16, rbac 10/10, cross_cutting 7/7, consistency_model 2/2.

**Skip reasons (all one category: PRD does not uniquely derive the asserted outcome — it contradicts it)**
- `state_machines/redraft_for_same_fiscal_year_supersedes_predecessor_and_uncounts_its_ballots` — design asserts a superseded **PROPOSED** budget's ballots get `counted` false; PRD 237 says "only the `DRAFT -> SUPERSEDED` leg clears the ballot record by setting `counted` false".
- `endpoints/contract_reinstatement_leaves_held_orders_held_and_never_moves_the_encumbrance` — design asserts no auto-resume; PRD 319 says reinstatement returns every `ON_HOLD` order whose `hold_reason` is `CONTRACT_SUSPENDED` to `SCHEDULED`.
- `errors/marking_a_cured_case_cured_again_returns_case_already_cured` — rung 11 scopes `ERR_CASE_ALREADY_CURED` to "hearing docketing only"; a repeat cure yields `ERR_CASE_ALREADY_TERMINAL`.
- `errors/certificate_request_for_a_past_closing_date_returns_cert_closing_date_past` — rung 56 / PRD 391 place that check on **issuance**, not on request.

Nothing was weakened, no `skip`/`xfail` marks, no placeholders.

**Notable design figures corrected against the PRD rather than skipped**
- Superseded `REQUESTED` certificate carries `requires_reissue` **false** (PRD 389), not true.
- Monthly allocation over 3334/3333/3333 bp of a 1,100,000 pool has drift **0** (366740 + 366630 + 366630), so `remainder_cents_allocated == 0` and no `remainder_cent_awarded` is true — the design's "remainder 1" is arithmetically wrong.
- The tender fan-out instance's unit balances were impossible because adoption posts no ledger charges (PRD 251/253); corrected to 0/0/35000, and the claim is adjusted (`DENY`) first because `TENDERED` requires an adjusted claim (PRD 360).
- The billing-run checkpoint instance used a `COLLECTION_COST` charge, which PRD 297 excludes from the late-fee base, and an age of 15 days, which cannot reach `LIEN_FILED` (PRD 229 rule 3 needs >= 90); redesigned with an `ASSESSMENT` of 170000 due 2026-05-05 -> capped fee 10000, balance 730000, age 138 -> `LIEN_FILED`.
- Response-body claims the PRD does not specify (e.g. unit posture inside the `POST /payments` body) were re-expressed as the immediate read-back plus the PRD-derived ledger row facts.

Every test carries exactly one trailing `Design: Corner/<section>/<instance.name>` line copied verbatim. Verification: `python3 -m pyflakes` clean on all nine files; citation/tag checker reports `tests: 203`, exit 0.

**Orchestrator independent re-verification (own script, not the agent's):** 203 test functions, 203 tagged, 0 untagged, 0 dual-tagged, 0 tags pointing at non-existent instances; 106/110 real design instances covered (Difficulty 18/18, Corner 88/92); the 4 uncovered instances are exactly the 4 documented skips; `grep` for `pytest.mark.skip|pytest.mark.xfail` across `test_suite/` returns nothing.

## Step 7: Run Tests and Iterate — 2026-09-01T01:09:00Z

All eight rounds green. Final gate satisfied.

**Exit summary**

Sweep gate: 8 parallel rounds of `prd-bench-local-run --isolation per-test-server`, all reporting **203/203 passed, 0 failed, 0 errors, 0 skipped** (~266 s per round), no runner processes left, zero `FAIL` lines in any round log. Results at `workspace/implementation/results.{1..8}.json`.

Iterations: 3 (two single-round harvests, then the full 8-round gate; the first 8-round launch was lost to an operational mishap, not a test failure — see note below). Baseline first round was 65/203.

Tests deleted: **none**. Suite is still 203 tests across 19 files, no skip/xfail anywhere.

**Assertions removed under STEP 1c** (partial coverage — BRANCH-ASYMMETRIC SIDE EFFECT, PRD §3.8 sets `decision_owner_id` only on the FINE and DISMISS branches and is silent for UPHOLD/VACATE):
- `test_suite/test_compensating_invariants.py` — `test_vacatur_on_the_second_round_decides_the_case_to_fine_vacated`: dropped the post-VACATE `decision_owner_id` assertion only.
- `test_suite/test_corner_state_machines.py` — `test_vacatur_at_the_appeal_round_restores_the_ledger_to_its_pre_fine_value`: same single assertion.

**Fixes in `test_helpers/`:**
- `assertions.py` — added `looks_like_instant`/`parse_instant`/`same_instant`/`assert_instant_equals` and made `assert_fields_equal` instant-aware; PRD pins three-fractional-digit rendering only for `created_at`/`updated_at`/`api_request_timestamp` and elsewhere pins the instant, so literal string equality was a mis-translation.
- `assertions.py` + `fixtures.py` — 18 sites of `"limit": 200` -> `"limit": 100`; PRD §2.3 caps `limit` at 100 inclusive, so the helpers were provoking a correct `ERR_VALIDATION` (**this one bug masked 105 tests**).
- `fixtures.py::open_special_assessment` — now returns the `open_ballot` response instead of the DRAFT creation response, so callers observe `approval_status == "BALLOTING"`.

**Fixes in `test_suite/`** (fixture/setup data that violated PRD preconditions, plus two mis-stated expectations):
- 16 files: same-line zero-fraction instant literals rewritten to `assert_instant_equals`; hand-fixed the four constant-valued stragglers (`INCUMBENT_START/END` in `test_resource_temporal_overlap.py:151,152,385`, `FINE_DECISION_AT` in `test_compensating_invariants.py:214`).
- `test_corner_cross_cutting.py`, `test_corner_rbac.py` — `insurance_cert_expires_at` moved to `2027-08-31T00:00:00Z` so it is at or after `effective_to` (PRD §3.6, else `ERR_CONTRACT_TERM_INVALID`); `element_class="STRUCTURE"` -> `"FACADE"` (not in the PRD enum); `post_installment` expected status 201 -> 200 (PRD §4 reserves 201 for resource-creating endpoints).
- `test_cross_entity_state.py::_bayline` — decoy claim is now DENY-adjusted then tendered, because PRD §3.4 requires a ballot's `funding_claim_id` to name a `TENDERED`/`IN_LITIGATION` claim; DENY chosen because it moves no association cash and so preserves the sibling baseline test's `operating_cash_cents` assertion.
- `test_corner_rbac.py::test_the_treasurer_may_not_record_the_board_award` — pre-award `approval_yes_count` expectation 0 -> 1, citing PRD §3.5: "When `subject_type` is `VENDOR_CONTRACT`, casting also recomputes that contract's `approval_yes_count`". The old expectation contradicted PRD; `pinned_element_version is None` and `status == "PENDING_APPROVAL"` are retained as the real evidence that the refused award pinned nothing.

**Fixes in `workspace/implementation/`: none.** Every defect traced to the test layers; the implementation's endpoint and error parity held throughout.

**Operational note:** the machine is concurrently running task 2187's own 8 runners, so `pgrep -f prd-bench-local-run` is not a valid completion signal here — poll with a task-scoped matcher. The first 8-round launch was killed at 76% because a poll call exceeded the default 120 s Bash timeout and the SIGTERM took the sweep's process group; relaunching under `setsid` with explicitly-timed polls fixed that. One round of the second launch showed a single `ConnectionResetError` on `test_one_ratify_call_allocates_every_unit_and_unblocks_the_billing_run` — a keep-alive transport reset with no server-side traceback, under 16 concurrent runners; it did not recur in the final 8/8 sweep and no code change was made for it.

**Orchestrator independent re-verification:** all 8 `results.*.json` parsed — every one `passed=203/203 failed=0 skipped=0 errors=0`; suite still 203 tests / 19 files; 0 files containing `pytest.mark.skip` or `pytest.mark.xfail`; 106 unique `Design:` tags (unchanged from Step 5, confirming no test was silently dropped); `grep` for `sqlite3|json.dump|pickle|shelve|/tmp/` across `implementation/*.py` returns nothing, so storage is still in-memory only.

## Step 8: Finalize PRD — 2026-09-01T01:19:00Z

Done. `PRD_FINALIZED.md` written.

**Line counts:** PRD.md 577 lines / 139,288 chars · PRD_FINALIZED.md 577 lines / 141,885 chars · Line delta 0 (+0.0%); character delta +2,597 (+1.9%) — all edits inline inside existing paragraphs; no new sections.

**Changes:**
- **§2.4 — insert** — pinned that every instant-/date-valued field (not just `created_at`/`updated_at`) is emitted as an ISO 8601 UTC instant with exactly three fractional digits and trailing `Z`, that inputs in any ISO form (including bare `YYYY-MM-DD` -> midnight UTC) are normalized to UTC, and that `period`/`effective_period` `YYYY-MM` strings are echoed verbatim — `serialize.py:9-16` + `clock.py:22-31`, `validation.py:160-171`.
- **§3.8 `UPHOLD` bullet — revise** — added that `decision_owner_id` is not rewritten and keeps the round-one value — `routes/cases.py:349-350`.
- **§3.8 `VACATE` bullet — revise** — same pin for the vacatur branch — `routes/cases.py:351-353`.
- **§4 preamble — insert** — pinned the exact 17-endpoint 201 class and stated that action endpoints returning an updated existing resource are 200 even when they mint ledger rows (installments, refund, cert issuance, `FINE` decision, claim adjust, closing) — `routes/assessments.py:175-203`, `response.py:25-31`.

**Per-edit pre-edit search log:**
1. **Datetime rendering** — (a) subject: textual rendering of every temporal field + input normalization. (b) enumerated: `serialize.py` (`_val`/`view`/`views` — single projection for every route, recursing into lists/dicts so `deductible_allocation`/`allocation_snapshot`/`applied_allocations` members follow the same rule), `clock.fmt`, `clock.parse`, `validation.require_dt`/`require_period`, `response._timestamp` (envelope stamp, wall clock — left untouched), plus a grep of every `*_at`/`*_date`/`*_from`/`*_to`/`*_start`/`*_end`/`*_on` assignment across `routes/` + `services/` + `db.py:114-120` confirming all are `datetime` and none is a client string echoed raw; computed reads checked separately (`core.py` statement + reserve-adequacy carry no instants; `certificates.py:158-177` reuses `serialize.view(cert)`). (c) adjustments: added "whenever such a field is non-null" (nulls stay null via `clock.fmt(None)`), made the field list explicitly illustrative ("among them"), added the `period`/`effective_period` carve-out so the rule cannot be over-applied to `YYYY-MM` strings.
2. **`decision_owner_id` on UPHOLD/VACATE** — (a) subject: every write and read of `decision_owner_id`. (b) enumerated: `grep -rn decision_owner_id` -> `cases.py:127` (born null), `:156` (list filter), `:329` (self-review guard reads it on UPHOLD/VACATE), `:342` (FINE writes), `:347` (DISMISS writes); confirmed no write on UPHOLD/VACATE (`:349-353`) and no other module (appeal `:357-387`, `routes/meetings.py` cancellation, `routes/planning.py` billing-run fine sweep) clears or rewrites it. (c) adjustment: wrote "keeps whatever value the round-one decision left on the case" rather than "still names the round-one decider", so the sentence stays true regardless of nullness and of how many appeal rounds precede.
3. **201-vs-200 class** — (a) subject: HTTP status of every endpoint. (b) enumerated: grepped all `response.created(`/`response.ok(` callsites across all nine route modules, then read the borderline ones: `assessments.py:175-203` installments (200), `:247-281` refund (200), `certificates.py:91-134` issue (200, posts `RESALE_FEE`), `cases.py:299-355` hearing decision (200, posts `FINE`), `claims.py` adjust (200, posts chargebacks), `ledger_routes.py:37-96` payments/charges/reverse (201), `:133-170` transfer-ownership (200), `planning.py:379` billing-run (201), `core.py:294-300` clock (200). (c) adjustment: replaced a vague "registration and drafting endpoints" draft with the exhaustive 17-path list, because the vague phrasing would have mis-described `POST /votes`, `POST /units/{unit_id}/payments|charges`, `POST /ledger-entries/{id}/reverse` and `POST /associations/{id}/billing-runs`, all 201 without being registrations or drafts.

**Items deliberately given NO PRD edit** (pure test-layer bugs already determined by PRD.md): the `limit: 200 -> 100` helper fix (§2.3/§2.9 rung 6 already cap at 100), `open_special_assessment` fixture returning the wrong response, `element_class="STRUCTURE"` (§3.6 enum), `insurance_cert_expires_at` vs `effective_to` (§3.6 / rung 55), the decoy claim needing `TENDERED` before ballot open (§3.4), and the pre-award `approval_yes_count` 0->1 expectation (§3.3 already says casting a `VENDOR_CONTRACT` vote recomputes it).

**Orchestrator independent re-verification:** 577 lines both files; `diff` of `^## ` headers is empty (no sections added/removed/renamed); only 8 diff lines total across exactly 3 hunks (82, 378-379, 409), confirming a genuinely minimal inline patch; §4 endpoint rows and §5 error rows unchanged at 82 and 81 respectively.

## Step 9: PRD Completeness Scan — 2026-09-01T01:50:00Z

Done. `PRD_COMPLETED.md` is complete.

## Exit summary

**Counts** — source `PRD_FINALIZED.md`: 577 lines / 141,885 chars. Completed `PRD_COMPLETED.md`: **577 lines / 171,245 chars** (char delta **+29,360**; line count deliberately held identical — every change is an in-paragraph insert or revision, no new paragraphs, no new sections, no table/heading changes). **71 lines changed: 48 ambiguity-pins, 23 mismatch-revisions.**

Constraints honored: `SCAFFOLD*.yaml` and `worklog.md` never read; implementation treated as the sole alignment target; Step 8's four prior edits (§2.4 instant rendering + `YYYY-MM` carve-out, §3.8 `UPHOLD`, §3.8 `VACATE`, §4 seventeen-endpoint 201 class) verified in place and left untouched.

### Changes

- §1 — revise — mismatch — the "manager who proposed a budget may not ballot on it" maxim documented as a no-op, `Budget` records no proposer field — `routes/planning.py`
- §2.1 — revise — mismatch — exactly two segregation checks exist, both on hearing-decision recording — `routes/cases.py:326-330`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:11`
- §2.2 — revise — mismatch — `api_request_timestamp` is real wall-clock, not the logical clock — `response.py:15`
- §2.2 — insert — ambiguity — `response_type` third value `"error"` — `response.py:47`
- §2.2 — insert — ambiguity — pagination `meta` keys absent on non-list responses; `has_more` formula — `response.py:34-39`
- §2.3 — insert — ambiguity — empty-string `limit`/`offset` treated as omitted; full enum-filter → `ERR_VALIDATION` list — `validation.py`
- §2.8 — insert — ambiguity — version bumps deduplicated per request via `g._bumped_rows` — `db.py:touch`
- §2.9 r7 — insert — ambiguity — owner scoping fires only when the role is literally `UnitOwner`, on three operations — `validation.py:owner_scope`
- §2.9 r11 — revise — mismatch — rung 11 evaluated **before** rung 10 on hearing docketing — `routes/cases.py:235-241`
- §2.9 r15 — revise — mismatch — vote casting performs no segregation check — `routes/assessments.py:283`
- §2.9 r33 — revise — mismatch — board-award recording raises it on any qualified-YES shortfall — `routes/elements.py:244-246`
- §2.9 r34 — insert — ambiguity — defined but unreachable guard — `routes/cases.py:279`
- §2.9 r60 — revise — mismatch — rung 60 also guards claim settlement, not only rescission — `routes/claims.py:328`
- §2.10 — insert — ambiguity — all 24 tunables validated as integers ≥ 0 — `routes/core.py:TUNABLE_DEFAULTS`
- §2.10 — insert — ambiguity — 21-name patchable set, any other key `ERR_VALIDATION`; empty body still a revision — `routes/core.py:PATCHABLE`
- §3.1 — insert — ambiguity — `email` is any non-empty string, no format check — `routes/core.py:180`
- §3.1 — insert — ambiguity — `REVERSAL` inherits `effective_period`, null `due_on`, carries no other provenance pointer — `services/ledger.py:reverse_entry`
- §3.1 — insert — ambiguity — open-charge ordering incl. insertion-order tiebreak — `services/ledger.py:open_charges`
- §3.1 — insert — ambiguity — `directed_bucket` validated against the six real buckets; silent statutory fallback — `services/ledger.py:apply_payment`
- §3.1 — insert — ambiguity — reversal endpoint refreshes SA money and restricted cash with no version bumps — `routes/ledger_routes.py`
- §3.1 — insert — ambiguity — `recompute_unit` always refreshes the same four derived fields incl. `transfer_blocked` — `services/ledger.py:recompute_unit`
- §3.1 — insert — ambiguity — statement is a pure read with exactly seven keys, `open_balances` keyed by all seven buckets — `routes/ledger_routes.py`
- §3.2 — insert — ambiguity — budget birth-field set — `routes/planning.py`
- §3.2 — insert — ambiguity — notice-mailing gates and error ids — `routes/planning.py`
- §3.2 — insert — ambiguity — notice return refused with `ERR_INVALID_MEETING_STATE` — `routes/planning.py`
- §3.2 — insert — ambiguity — ratify order 12→13→14→25, then rungs 35/43/49 on the adoption branch only — `routes/planning.py`
- §3.2 — insert — ambiguity — allocation participant ordering `(-interest_bp, created_at, _seq)` — `services/alloc.py:participants`
- §3.2 — revise — mismatch — adoption cascade hop five runs unconditionally — `routes/planning.py:adoption_cascade`
- §3.3 — insert — ambiguity — `scheduled_end` must be strictly after `scheduled_start`, else `ERR_VALIDATION` — `routes/meetings.py:28`
- §3.3 — insert — ambiguity — send-notice/convene error ids, optional attendance list, FK resolution before state gates — `routes/meetings.py:68-110`
- §3.3 — insert — ambiguity — a docketed case with `hearing_round` 0 is untouched by cancellation — `routes/meetings.py:168-169`
- §3.3 — revise — mismatch — no segregation on vote casting; rung 8 evaluated before rung 7 — `routes/assessments.py:316-320`
- §3.3 — revise — mismatch — cast-time `approval_yes_count` formula is broader than the award-time tally — `routes/assessments.py:28-34`
- §3.4 — insert — ambiguity — SA birth-field set — `routes/assessments.py:59-77`
- §3.4 — revise — mismatch — open-ballot funding-claim precondition is `ERR_INVALID_CLAIM_STATE`; check order — `routes/assessments.py:117-133`
- §3.4 — insert — ambiguity — survivor tie-break falls through to insertion order — `services/assessment.py:survivors`
- §3.4 — insert — ambiguity — installment roster is every unit as it stands at posting time — `services/alloc.py:participants`
- §3.4 — insert — ambiguity — direct `UNFUNDED → FULLY_COLLECTED`; restricted-cash refresh decoupled from the version bumps — `services/assessment.py:on_payment_collection`
- §3.4 — revise — mismatch — refund is a plain unallocated credit, no reverse allocator — `routes/assessments.py:270`
- §3.5 — insert — ambiguity — fiscal year of a `YYYY-MM` period from `fiscal_year_start_month` — `routes/planning.py:fiscal_year_of_period`
- §3.5 — insert — ambiguity — the adoption snapshot is the only roster the run consults — `routes/planning.py`
- §3.5 — insert — ambiguity — late-fee scope and per-period dedupe checked after computing the fee — `routes/planning.py:late_fee_for`
- §3.5 — insert — ambiguity — both contract sweeps may fire on one contract in one pass, `created_at` order — `services/contracts.py:63-91`
- §3.5 — insert — ambiguity — certificate sweep scoped to this association's units — `routes/planning.py`
- §3.6 — insert — ambiguity — certificate renewal is ungated by contract status, clock, or `effective_to` — `routes/elements.py:179-188`
- §3.6 — revise — mismatch — on submit the element gate precedes the term gates — `routes/elements.py:200-207`
- §3.6 — revise — mismatch — any qualified-YES shortfall → `ERR_AGENDA_KIND_MISSING`; element gate first — `routes/elements.py:224-246`
- §3.6 — insert — ambiguity — clock outside the term on activate is `ERR_INVALID_CONTRACT_STATE` — `routes/elements.py:264-266`
- §3.6 — insert — ambiguity — reinstate order/error ids; `effective_from` not re-tested — `routes/elements.py:305-317`
- §3.6 — revise — mismatch — `is_emergency` is descriptive; creation does not gate on contract status — `routes/elements.py:355-399`
- §3.6 — insert — ambiguity — non-`ACTIVE` contract on start → `ERR_INVALID_CONTRACT_STATE` — `routes/elements.py:455`
- §3.6 — insert — ambiguity — reserve report takes `method` as a query param; `data` has exactly six keys — `routes/core.py:129-170`
- §3.7 — insert — ambiguity — assign-adjuster error ids — `routes/claims.py:139-144`
- §3.7 — insert — ambiguity — no operating-cash gate on any branch; chargeback `effective_period` from the clock — `routes/claims.py:166-231`
- §3.7 — revise — mismatch — a zero-total-`heated_sqft` participant set leaves the residue unallocated — `money.py:floor_then_topup`
- §3.7 — insert — ambiguity — settlement litigation gate error id and order — `routes/claims.py:322-329`
- §3.7 — revise — mismatch — all three tender preconditions report `ERR_INVALID_CLAIM_STATE`; SA money-refresh hop added — `routes/claims.py:265-285`
- §3.8 — insert — ambiguity — terminal-before-transition on notice; `ERR_UNIT_NOT_FOUND`; closed predecessor window — `routes/cases.py:176-191`
- §3.8 — insert — ambiguity — terminal-before-transition on cure recording — `routes/cases.py:202-207`
- §3.8 — revise — mismatch — meeting-status failure is `ERR_INVALID_MEETING_STATE` not `ERR_AGENDA_KIND_MISSING`; full nine-gate order; `CURED` first; dual body key — `routes/cases.py:222-285`
- §3.8 — revise — mismatch — rung 34's position and its unreachability — `routes/cases.py:279`
- §3.8 — insert — ambiguity — round/outcome legality is `ERR_INVALID_STATE_TRANSITION`, tested before the meeting gates — `routes/cases.py:313-317`
- §3.8 — revise — mismatch — no branch-specific seating gate on the `FINE` branch — `routes/cases.py:333`
- §3.8 — revise — mismatch — five vacatur hops, not four; reversal only when the `FINE` row is still `POSTED` — `routes/cases.py:78-94`
- §3.8 — revise — mismatch — owner-scope gate precedes the terminal and transition checks; slot count floored at 0 — `routes/cases.py:365-381`
- §3.9 — insert — ambiguity — superseded certificates bump their own version; `ISSUED` certificates untouched — `routes/certificates.py:37-42`
- §3.9 — insert — ambiguity — fiscal-year-containing formula with a non-January start — `services/certificate.py:109-113`
- §3.9 — insert — ambiguity — `RESALE_FEE` bucket/period/`due_on`; exactly one `Unit.version` bump across issuance — `routes/certificates.py:116-132`
- §3.9 — revise — mismatch — wrong-unit certificate → `ERR_NO_VALID_CERTIFICATE`; response is the updated **Unit**, 200 — `routes/ledger_routes.py:150-170`
- §3.9 — insert — ambiguity — questionnaire is ungated by status; full certificate view plus exactly three added keys — `routes/certificates.py:158-177`

### Two findings worth flagging

- **`ERR_SAME_MEETING_REHEARING` is unreachable.** Rung 34 compares the target meeting against the case's `hearing_meeting_id`, but both routes into `APPEALED` (owner appeal, meeting cancellation) clear that field first. Pinned as a defined-but-unraised code in §2.9 and §3.8 rather than removed.
- **`approval_yes_count` has two competing formulas.** Vote casting recomputes it over all counted `BOARD_DIRECTOR` YES votes with no meeting/agenda filter; the award endpoint overwrites it with a `CONTRACT_AWARD`-and-in-session-or-adjourned count. Pinned both, with only the narrower one governing admission.

**Orchestrator independent re-verification:** `PRD_COMPLETED.md` 577 lines / 171,245 chars (`PRD_FINALIZED.md` 577 / 141,885 — delta +29,360 chars, 0 lines). Heading parity exact at every level (1 `#`, 5 `##`, 19 `###`, 2 `####`) and a `diff` of all heading lines is empty — no section added, removed, or renamed. `diff` reports 68 hunks, **every one a `c` (change) hunk with zero `a`/`d` hunks**, so all 71 changed lines are genuine in-place paragraph revisions rather than appended prose. §4 endpoint rows and §5 error rows preserved at 82 and 81. All three Step 8 edits still present in the completed file. File ends on a complete §5 table row with a trailing newline — not truncated. The three `SCAFFOLD*.yaml` files carry their Step 2 mtimes (19:47 / 20:23 / 20:47), unmodified by Steps 7–9.

## Pipeline complete — 2026-09-01T01:52:00Z

All nine steps have valid on-disk artifacts. Final state: SCAFFOLD.yaml 3,843 lines · SCAFFOLD_DIFFICULTY_DESIGN.yaml 2,211 · SCAFFOLD_CORNER_DESIGN.yaml 5,803 · PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md 577 each · test_helpers/ 10 files · test_suite/ 19 files / 203 tests · implementation/ 25 Python modules / 4,593 lines · 8/8 isolated sweep rounds at 203/203 passed, 0 failed, 0 skipped, 0 errors. Steps 1 and 3 were preserved from the original run and never redone; the task directory was never renamed; `worklog.md` has only ever been appended to.
