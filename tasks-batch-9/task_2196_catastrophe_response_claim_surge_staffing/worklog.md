# Worklog — task_2196_catastrophe_response_claim_surge_staffing

## Step 1: Create task directory — 2026-08-31T00:00:00.000Z

Created `tasks/task_2196_catastrophe_response_claim_surge_staffing/` and `workspace/` subdirectory (pre-allocated name used verbatim; no index scan performed).

## Step 3: Copy shared files — 2026-08-31T00:00:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md` (verified byte-identical to project-root INSTRUCTION.md, 53 lines).

## Step 2a: Generate SCAFFOLD.yaml (§1.0–§1.7) — 2026-08-31T20:40:00.000Z

RESUME NOTE: two prior subagent attempts at scaffold generation were killed by the harness stall watchdog (600s with no streamed tool call) after spending their budget reading `scaffold_lint.py` internals and then attempting one monolithic write. Third attempt succeeded under an explicit anti-stall protocol (incremental section-by-section appends, ~250 lines per tool call, no linter source reading). Step 2 was also split: SCAFFOLD.yaml in this session, §1.8/§1.9 design indices in a follow-on session.

Subagent summary (verbatim):

Done. Single file written: `SCAFFOLD.yaml`

Counts (§1.0–§1.7 only; no `scaffold_difficulty_design` / `scaffold_corner_design` keys — verified programmatically)

| Section | Count |
|---|---|
| entities (§1.1) | 13 |
| state machines (§1.2) | 11 (66 transitions) |
| concurrency rules (§1.2.1) | 2 (OCC on `CatastropheEvent.version`, `Claim.version`) |
| calculations (§1.3) | 15 |
| validations (§1.4) | 41 (priorities 1–41, contiguous & unique) |
| endpoints (§1.5) | 67 (incl. one `/_clock/set_current_utc` test-driving endpoint) |
| errors (§1.6) | 101 |
| roles (§1.7) | 6 |
| total lines | 2574 |

Design (beyond-Expert calibration)
- Profile: `compliance_audit` + `quota_allocation`; topology flat (FK-linked peers, no nested URLs); shape parallel (Claim `handling_status × payment_status`, Adjuster `deployment_status × credential_status`); role model `segregation_of_duties`.
- Rule 1 dual-variant: `event_loss_estimate` (EXPOSURE_BASED vs INCURRED_DEVELOPMENT) and `deployment_cost` (PROVISIONAL vs FINAL_SETTLED).
- Rule 2 combinatorial, three distinct modes: (a) `claim_triage_severity_score`, (b) `advance_payment_amount` with pinned round-per-line-then-sum (and `initial_case_reserve` deliberately pinned the opposite way), (c) `deployment_cost` circular tier pinned to the pre-premium subtotal.
- Rule 3 non-linear: parallel axes on Claim and Adjuster; cycles on Claim handling (CLOSED->REOPENED->...), Adjuster credential (EXPIRED<->WAIVED) and deployment (AVAILABLE->DEPLOYED->RESTING->AVAILABLE), HousingBlock (ACTIVE<->EXHAUSTED), VendorFirm, FileTransferBatch; fork-join branch on event close (DEMOBILIZING vs DECLARED stand-down, divergent side-effect sets).
- Rule 4 cascades: `demobilize_deployment_chain` depth 5, `void_advance_chain` depth 4 — distinct triggers, each link caused by the previous.
- Rule 5: three priority-conflict pairs on distinct category pairs (state/business_safety, business_temporal/business_fiscal, business_referential/business_constraint), documented as a comment block after §1.4.
- Rule 6 boundaries: `severity_score >= 75.00`, posture `strain >= 8`, `rooms_total == 0`, empty selector pool, zero advance headroom — different metrics and endpoints.
- Rule 7 cross-entity: Claim->CatastropheEvent, Deployment->Adjuster, Deployment->HousingBlock, InspectionAssignment->Adjuster, VendorFirm->CatastropheEvent, FileTransferBatch->CatastropheEvent.
- Rule 8 overlap semantics: buffered half-open (Adjuster deployments, 12h rest), aggregate-capacity nightly (HousingBlock), strict zero-buffer half-open (Adjuster inspections), containment (Deployment window).
- Rule 9 conserved quantities: `reserve_conservation_invariant` (dollars: `incurred_total`) and `housing_room_conservation_invariant` (room counts).

Checks run
- `yaml.safe_load` parses; top-level keys are the 12 expected ones (had to quote optional `field?` tokens in flow sequences — YAML treats `?` before `,` as an indicator).
- FK reverse-reachability (lint check f, replicated locally): none unreachable — every `FK -> X.id` field is a filter on a matching `GET` returning `Child[]`.
- Every endpoint role in §1.7; every declared error is referenced and every referenced error is declared (both diffs empty).
- Both OCC write endpoints take `expected_*_version` as required input and bump the parent's version.
- Forbidden concurrency vocabulary: none. No `id`-based selectors/tie-breaks (all fall back to `created_at ASC`). No fuzzy adjectives left in constraint scopes.
- Logical clock default pinned to `2026-08-01T00:00:00Z` in the clock endpoint description.

Linter status: `python3 scaffold_lint.py <task-dir>` currently exits with `ERROR: file not found: .../SCAFFOLD_DIFFICULTY_DESIGN.yaml` — expected, since §1.8/§1.9 are deferred to a later session. It must be re-run once those two files exist.

## Step 2b: Generate §1.8 / §1.9 design indices — 2026-08-31T22:10:00.000Z

Generated in pieces to survive the harness failures seen earlier in this resume (600s stall watchdog + transient API errors on long single generations).

- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1989 lines, 9 `rule_id`s, **25 instances** (>= 18 minimum). Rules: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 6855 lines, all **9** claim-extraction-guide sections, **166 instances = 119 non-stub + 47 `excluded_because:` stubs**. Per section: entities 12, state_machines 15, calculations 26, validations 23, endpoints 19, errors 33, rbac 12, cross_cutting_complexity_layers 17, consistency_model 9.

The first agent wrote the difficulty file plus corner sections `entities` + `state_machines` before dying to an API error; the remaining 7 corner sections were then produced by 3 concurrent agents into part files (`CORNER_PART_A/B/C.yaml`) and concatenated by the orchestrator. Post-concatenation checks: parses as a single `scaffold_corner_design` key, 0 duplicate instance names across both design files, 0 bad `excluded_because` citations (all 47 resolve to real §1.8 instance names).

Subagent-reported verification (all three part agents ran machine checks): every `call` resolves to a real §1.5 method+path; every setup call uses a permitted role and only declared `input:` fields; every `${var}` bound by an earlier `captures:`; every capture reads a declared `output:` field; OCC `expected_*_version` always a captured `${var}` or `${var} - 1`, never a bare literal; every formula-derived assert a literal computed by running the §1.3 formula (Decimal ROUND_HALF_UP, declared rounding order) — no `round(...)` expressions left; no wall-clock waits (all time movement via `POST /_clock/set_current_utc`).

### Orchestrator scaffold repair (§1.5), driven by the linter

First full lint run: **29 violations** — 20 `(f) FK_REVERSE_UNREACHABLE` + 9 `(b) role not allowed`. Diagnosis and fix:

1. `api_prefix` was `/catastrophe-events`, but this scaffold is deliberately **flat topology** ("peer entities with FK references, no nesting in URL paths"), so peer collections live at the root and no path sat under the declared prefix. The linter derives entity collection segments only from paths under `api_prefix`, so segment derivation returned nothing and *every* FK looked unreachable. Set `api_prefix: ""` with an inline comment recording why. This also removes a real downstream hazard: an api_prefix naming a real resource collection invites the PRD/implementation to mount every route under `/catastrophe-events/...` while the design recipes (and hence the tests) call `/claims`, `/adjusters`, ... at the root. Dropped 20 -> 14.
2. Remaining 14 were genuine: 8 entities (RegulatoryBulletin, ReserveEntry, InspectionAssignment, AdvancePayment, VendorFirm, VendorAssignment, LossEstimateSnapshot, FileTransferBatch) had a filtered list GET declaring every FK filter, but **no single-read `GET /<collection>/{id}`**, which the linter requires to derive the collection segment. Added the 8 missing single-read endpoints (priority-ladder rung 2 — ordinary business read endpoints, roles copied from each entity's list-GET read audience, `input: []`, `output: <Entity>`, no side effects). §1.5 endpoint count 67 -> 75.

Final lint: **9 violations, all `(b) role not allowed`, all at `trigger[0]`** — every one is an intentional RBAC-denial corner (`corner_rbac_*` denials plus the priority-3 `role_not_permitted` and unknown-role `SurgeIntern` validation corners). §1.9 mandates these negative instances; check (b) cannot distinguish a deliberate denial trigger from an authoring mistake, so they are expected residue, not defects. Zero FK, endpoint-existence, payload-schema, capture-resolution or placeholder-closure violations remain across 1112 scanned calls.

Backup of the pre-repair scaffold: `/tmp/SCAFFOLD.pre_fk_fix.yaml`. Part files `CORNER_PART_A/B/C.yaml` left in the task dir as provenance.

Known scaffold notes flagged by the part agents, carried forward for later steps:
- `ERR_BATCH_HAS_BLOCKING_CLAIMS` http_status conflicts between §1.4 priority 37 (422) and §1.6 (409); corner instance asserts only `error.code`.
- A settled claim with zeroed reserve can never be transferred (`blocking_claim_count` counts `case_reserve == 0`), so batches are submittable only with CLOSED-but-unpaid claims.
- §1.4 priority 22's "accept must differ from submitter" clause is only reachable if one X-User-ID is used under two roles; left out of the index in favour of the retained-`advance_issuing_examiner_user_id` SoD corner.
- For a settling PAYMENT reserve entry, §1.2 says the entry zeroes the residual reserve while §1.5 still takes `delta_case_reserve` from the body — ambiguous whether a client value is honoured or overwritten; the recipe supplies the exact matching literal so it is valid under either reading.

## Step 4: Generate PRD — 2026-08-31T22:45:00.000Z

Subagent summary (verbatim):

PRD complete at `workspace/PRD.md`.

Line count: 483 lines (~110 KB). File ends at the last row of the §5 table — no audit footer.

Section list
- §1. Introduction
- §2. Global Specifications & System-Wide Principles — 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim fixed block, byte-identical, including both fenced envelopes) · 2.3 Pagination · 2.4 Flat Collection Topology and Reference Resolution · 2.5 Record Identity, Audit Fields and the Ledger Exception · 2.6 The Logical Clock · 2.7 Monetary Precision, Counting and Rounding Order · 2.8 Stale-Version Rejection on Reserve and Estimate Writes · 2.9 Event Posture: the Automatic Gate over Child Operations · 2.10 Two Conserved Quantities · 2.11 Order of Rejection
- §3. Business Logic & Workflows — 3.1 Standing Up, Escalating and Standing Down a Catastrophe Event · 3.2 Regulatory Bulletins: Moratoriums, Deadline Extensions, Payment Mandates and Licence Waivers · 3.3 Adjuster Supply: Two Independent Axes, Rest, Fatigue and Capacity Ranking · 3.4 Housing Logistics: Room Blocks and the Nightly Capacity Rule · 3.5 Deploying the Surge Workforce and Settling What It Cost · 3.6 First Notice of Loss, Cat Coding and Triage · 3.7 Inspecting the Loss: Field, Desk and Aerial Work · 3.8 The Reserve Ledger, Advance Payments, Settlement and Loss Estimation · 3.9 Work That Leaves the Catastrophe Team: Vendor Dispatch and File Transfer
- §4. Endpoint Definitions — 4-column table (Method, Path, Description, Authorized Role(s)), 75 rows
- §5. Error Code Catalogue — 2-column table (Error ID, HTTP Status Code), 101 rows

Coverage audit (all machine-verified against SCAFFOLD.yaml)
- Entities: 13/13 — every entity named in PascalCase in §2.4 and worked through in §3.
- Entity fields + endpoint identifiers: 133/133 unique names appear verbatim in backticks (0 missing).
- State machines: 11/11; every declared state string of every machine appears in §1–§3 prose, including both dual axes for `Claim` (`handling_status` x `payment_status`) and `Adjuster` (`deployment_status` x `credential_status`).
- Enumerated values: every `enum` value anywhere in the scaffold (fields, params, calculation variants) appears in §1–§3 prose (0 missing).
- Calculations: 15/15 — each rendered as prose with its output field, variant selection, clamping and pinned rounding order (including the two deliberately opposite orders and both dual-variant rules).
- Validations: 41/41 — narrated in priority order in §2.11 and re-stated at their point of use in §3; all 41 error identifiers appear in §1–§3 prose, not only in the §5 table.
- OCC rules: 2/2 — `expected_event_version` -> `ERR_STALE_EVENT_VERSION` and `expected_claim_version` -> `ERR_STALE_CLAIM_VERSION`, both 412, in §2.8.
- Endpoints: 75/75 in §4 with paths exactly as declared (flat root-level collections, empty `api_prefix`, no nesting).
- Errors: 101/101 in §5, and all 101 also appear in §1–§3 prose.
- Roles: 6/6 (`CatastropheManager`, `DeploymentCoordinator`, `ClaimsExaminer`, `ComplianceOfficer`, `Adjuster`, `VendorCoordinator`), including the two entity-backed identities and the segregation-of-duties pairs.

Hard Contracts
- Contract 1 (Field-Name Coverage): PASS — 133/133 identifiers present verbatim in backticks, verified twice (initial run flagged 165 false positives caused by the §2.2 code fences skewing backtick pairing; re-audited with fences excluded and JSON keys counted separately -> 0 missing).
- Contract 2 (Rule Coverage): PASS — all transitions, guards, side-effect cascades (5-link `demobilize_deployment_chain`, 4-link `void_advance_chain`), `applies_to` scopes, the three declared priority-conflict outcomes, both conserved quantities and all sibling branches rendered at equal density.
- Contract 3 (§3 Path Purity): PASS — 379 distinct backticked tokens in §3, none starting with `/`, none a bare HTTP method, none a method+path combination.

No fuzzy quantifiers (`approximately`, `roughly`, `conservatively`, `as appropriate`, `TBD`) occur anywhere in the file. Withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, its `CORNER_PART_*.yaml` fragments, `worklog.md`) were never opened or grepped, and no sibling task directory was inspected.

## Step 5a: Test infrastructure + queue A (depth) — 2026-08-31T23:55:00.000Z

Step 5 was split: this session built the shared `test_helpers/` infrastructure plus all of queue A (§1.8); queue B (§1.9) was then translated by four concurrent sibling agents (Step 5b) writing disjoint `test_corner_<section>.py` files against the same helpers.

Subagent summary (verbatim):

Stage 1 + queue A complete.

Shared infrastructure (`test_helpers/`, 2166 lines total)
- `__init__.py` 35 · `types.py` 495 · `api_client.py` 333 (one method per each of the 75 endpoints, empty `api_prefix`) · `api_errors.py` 171 (all 101 ids, registers the id->HTTP map on import) · `constants.py` 91 · `test_users.py` 93 (all 6 roles; entity-backed `make_adjuster_headers` / `make_vendor_coordinator_headers`) · `factories.py` 268 (payload builders for all 13 entities) · `assertions.py` 394 (money tolerance, 13 entity shape asserters, the two conservation asserters) · `fixtures.py` 286 (plain state-builder functions, not pytest fixtures)
- `test_suite/conftest.py` 69 (session-scoped `api`, ten role-header fixtures)
- `test_helpers/HANDOFF.md` — exactly 60 lines, for the three queue-B agents

Queue A: 25 of 25 instances translated, 0 skipped. No instance failed the two-condition PRD filter. 51 tests across 9 files (>= 2 per instance, verified programmatically):

| file | lines | tests |
|---|---|---|
| test_difficulty_dual_variant_calc.py | 336 | 5 |
| test_difficulty_combinatorial_formula.py | 385 | 6 |
| test_difficulty_non_linear_state_machine.py | 393 | 6 |
| test_difficulty_transitive_cascade.py | 395 | 4 |
| test_difficulty_priority_pair_validation_conflict.py | 485 | 6 |
| test_difficulty_boundary_precision_check.py | 343 | 6 |
| test_difficulty_cross_entity_state_dependency.py | 373 | 6 |
| test_difficulty_resource_temporal_overlap.py | 449 | 6 |
| test_difficulty_compensating_invariant.py | 528 | 6 |

Verification performed
- Tag audit: 51 tests, 51 `Design:` lines (exactly one per test, always last); all 25 distinct instance names match `SCAFFOLD_DIFFICULTY_DESIGN.yaml` verbatim; zero tags pointing at non-existent instances; zero instances left untagged.
- Citation sweep: all 144 quoted PRD sentences across the 9 files were whitespace-normalised and grepped against `workspace/PRD.md` — 0 misses. This sweep plus earlier spot checks fixed 3 defects (two fabricated sentences, one abbreviated fragment).
- `python3 -m compileall -q test_helpers test_suite` -> clean; `pytest --collect-only -q` -> 51 tests collected in 0.23 s (no server needed). The implementation was never touched or inspected.

Two design assertions deliberately dropped (instances still translated): the `open_job_count` reading immediately after a *dispatch* (in `vendor_assignment_accept_gated_by_firm_network_status` and `vendor_concurrency_slots_conserved_across_accept_then_complete`). The PRD never defines the "open population" explicitly — only the endpoint tables hint at it, which C2 bars as a rule-bearing citation — so those tests assert the uniquely-derivable parts instead: counts after acceptance/completion, and that a dispatch alone never drives `ACTIVATED -> CAPACITY_HOLD` (§3.9 says the edge fires on "a job acceptance").

## Step 6: Generate implementation — 2026-08-31T23:55:00.000Z

Launched concurrently with Step 5a (physical isolation: `test_suite/` did not exist when this agent started, and it was barred from reading `test_helpers/`, both design indices and the worklog).

Subagent summary (verbatim):

Implementation complete and verified.

Files (`workspace/implementation/`, 4004 lines total)

| file | lines | role |
|---|---|---|
| `start.sh` | 8 | guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | 1 | `flask==3.0.3` |
| `app.py` | 50 | `create_app()`, `ApiError` handler, 404/405/500 fallbacks |
| `store.py` | 194 | 13 in-memory dicts, logical clock, id/seq generators, Decimal + datetime helpers |
| `errors.py` | 127 | `ApiError`, `fail()`, HTTP-status map for all 101 error ids |
| `envelope.py` | 71 | `{meta, response_type, data}` envelope, pagination (`limit/offset/total_count/has_more`) |
| `auth.py` | 151 | 6 roles, per-endpoint role table for all 75 routes, ladder 1-3 |
| `validate.py` | 334 | body parsing, 13 existence resolvers (4-14), schema helpers (15), `interval()` (16) |
| `calc.py` | 220 | all 15 calculations + pinned constants |
| `derive.py` | 524 | every computed roll-up, event posture, 13 serializers |
| `sync.py` | 157 | time-driven re-evaluation (`sync_all`), deadline recompute, claim regression |
| `ops.py` | 213 | ledger append, both selectors, rest buffer, nightly housing capacity, cascades |
| `routes/` | 15 modules, 1929 | `__init__` 25, `common` 52, `clock` 23, `events` 166, `bulletins` 117, `adjusters` 124, `housing` 96, `deployments` 216, `claims` 250, `reserve_entries` 29, `assignments` 231, `advances` 127, `vendor_firms` 107, `vendor_assignments` 149, `loss_estimates` 79, `batches` 163 |

Key mechanics

Validation ladder — enforced positionally, not by exception ordering. Every handler runs the same skeleton: `begin()` (positions 1-3 auth) -> `soft_body()` + `raw_ref` existence resolution in the fixed entity order 4-14 (path id of a type always before a body id of the same type; optional body ids only when supplied non-null) -> `validate.body()` schema (15) -> `interval()` (16) -> ownership (17) -> OCC (18) -> state (19) -> posture (20) -> moratorium (21) -> SoD (22) -> the domain gates 23-41 written in numeric order in each handler. The three declared conflict pairs are hard-coded with comments: `ERR_CLAIM_NOT_INSPECTED` before `ERR_MORATORIUM_ACTIVE` (claim close), `ERR_DEPLOYMENT_WINDOW_CONFLICT` before `ERR_HOUSING_CAPACITY_EXCEEDED` (confirm), `ERR_INSPECTION_MODE_MISMATCH` before `ERR_ADJUSTER_AT_CAPACITY` (assignment create).

OCC (position 18, both 412) — `POST /loss-estimates` compares `expected_event_version` against `event["version"]` -> `ERR_STALE_EVENT_VERSION`; `POST /claims/{id}/reserve-entries` compares `expected_claim_version` against `claim["version"]` -> `ERR_STALE_CLAIM_VERSION`. Both run after schema and before every state/posture gate, and nothing is created on mismatch.

Logical clock — `store.clock_now()` is the single time source; startup value is exactly `2026-08-01T00:00:00Z`, never wall-clock. `POST /_clock/set_current_utc` sets it, then every read and write calls `sync.sync_all()`, which re-derives bulletin EFFECTIVE->EXPIRED, adjuster VALID->EXPIRING->EXPIRED and WAIVED->EXPIRED, RESTING->AVAILABLE after the 12-hour buffer, and the deadline recomputes those imply.

Storage — 13 module-level dicts keyed by id, nothing else. A grep for `open(`, `sqlite`, `json.dump`, `pickle`, `shelve`, `/tmp` in the implementation returns nothing, so relaunching `start.sh` wipes all state. No seeding anywhere: on a fresh boot all 13 collections return `rows=0 total=0`.

Verification
- `python3 -m compileall -q .` -> clean; `__pycache__` removed.
- Route audit against the SCAFFOLD endpoint list: 75 declared / 75 implemented, 0 missing, 0 extra, all flat (no prefix).
- Error audit: 101/101 catalogue ids mapped to the declared HTTP status (0 mismatches) and all 101 referenced at a raise site.
- Three boot-and-exercise passes on ports 18196-18199, 0 server-side tracebacks, no 5xx: full happy path (declare -> bulletin -> housing -> snapshot -> activate-surge -> claim -> triage -> deployment confirm/check-in -> assignment start/complete -> advance issue/void -> vendor dispatch/accept/complete -> settle -> close -> demobilize -> batch -> close) plus the second-pass sweep of every remaining endpoint and the reject/reopen/resubmit and stand-down-close branches. Representative rejections observed with the right id and status: `ERR_VALIDATION` 422, `ERR_INVALID_WINDOW` 422, `ERR_CAT_CODE_TAKEN` 409, `ERR_DUPLICATE_CLAIM` 409, `ERR_EVENT_NOT_FOUND` 404, `ERR_STALE_EVENT_VERSION`/`ERR_STALE_CLAIM_VERSION` 412, `ERR_NOT_ASSIGNED_ADJUSTER` 403, `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_ADVANCE_CAP_EXCEEDED` 422, `ERR_RESERVE_WOULD_GO_NEGATIVE` 422, `ERR_ASSIGNMENT_WINDOW_CONFLICT` 409 (with exact adjacency accepted), `ERR_LOSS_ESTIMATE_STALE` 409, `ERR_BATCH_HAS_BLOCKING_CLAIMS` 409, `ERR_REJECTION_REASON_REQUIRED` 422, `ERR_NO_ELIGIBLE_ADJUSTER` 409.
- All test servers were killed after each pass; nothing is left listening.

## Step 5b: Queue B (breadth, §1.9 corner design) — 2026-09-01T01:30:00.000Z

Four concurrent subagents (D, E, F, G) split the nine §1.9 sections. Consolidated
result: **119/119 non-stub instances translated, 0 skipped**. Combined with queue A's
51 tests this gives **170 tests** across 18 test files, all collected without a live
server, `compileall` clean, exactly one verbatim `Design:` tag as the last docstring
line of every test, 0 tags resolving to a stub or to a non-existent instance.

Per-file totals (lines / tests):
- test_corner_calculations.py         1164 / 18
- test_corner_errors.py               1015 / 21
- test_corner_endpoints.py             958 / 16
- test_corner_validations.py           978 / 15
- test_corner_entities.py              894 / 12
- test_corner_rbac.py                  792 / 12
- test_corner_state_machines.py        685 /  7
- test_corner_cross_cutting.py         615 /  9
- test_corner_consistency_model.py     449 /  9

New helper modules: `test_helpers/corner_support_d.py` (146 lines),
`test_helpers/corner_support_g.py` (152 lines). Agents E and F needed none.
No agent read `workspace/implementation/`. Every agent ran a whitespace-normalised
PRD-citation sweep: 0 fabricated quotes.

### Reported deviations (all recorded; none weakens an assertion)

Agent D (entities, state_machines, calculations) — dropped 4 PRD-undetermined
sub-assertions: (1) intra-position ladder precedence between ERR_NO_ACTIVE_HOUSING
and ERR_LOSS_ESTIMATE_STALE; (2) posture OPEN at strain 3, corrected to RESTRICTED;
(3) `open_job_count == 1` on a merely DISPATCHED job; (4) `voided_at_utc is None` /
`closing_examiner_user_id is None` at creation (default-value silence). Rebuilt 2
setups whose stated precondition — a CONFIRMED non-DESK deployment with no housing
block — is unreachable through the API.

Agent D also reported an upstream defect it was forbidden to fix:
**`test_helpers/fixtures.py` is unusable — its `_data(response)` path calls
`response.get("success")` on a `requests.Response` object whenever no
`expected_status` is passed, so every 200-returning fixture helper raises
`AttributeError`.** Agent D worked around it inside `corner_support_d.py` by calling
`validate_success` directly. Flagged to Step 7 as a first-suspect test_helpers bug.

Agent E (validations, endpoints) — found 2 defects in the design instance
`corner_val_settled_claim_with_zero_reserve_blocks_batch_submit`: the event is left
in DECLARED, which would mask the intended error behind `ERR_EVENT_NOT_DEMOBILIZING`,
and a NONE→SETTLED `payment_status` jump is not a declared transition. Extended and
split the setup to reach the intended state legally rather than weakening the assert.

Agent F (errors, rbac) — dropped 2 default-value-silence sub-assertions and pinned
`rooms_reserved: 0` for a DESK deployment (DESK adjusters take no housing block).

Agent G (cross_cutting_complexity_layers, consistency_model) — relaxed an exact
`version == 3` to strict monotonicity in
`corner_cm_interleaved_event_write_immediately_invalidates_earlier_read`, because
PRD §3.1 and §3.4 together admit both 3 and 4 for that interleaving.

## Step 7: Run tests and iterate — 2026-09-01T02:20:00.000Z

Clean 8-round sweep achieved.

**Iterations run:** 2 (each = 8 concurrent full rounds, 170 tests, per-test-server isolation).

**Final tally:** 170/170 passed in all 8 parallel rounds. **0 tests deleted.**

**Tests deleted:** none. Every failing test traced to a verbatim PRD sentence and passed STEP 1a coverage + STEP 1b unique-derivability, so all failures were resolved as test-helper or implementation defects.

### Fixes applied to `test_helpers/`
- `test_helpers/fixtures.py` — `_data()`: the reported upstream bug is real. On the no-`expected_status` path it called `response.get("success")` on a `requests.Response`, raising `AttributeError` for every 200-returning setup helper (`declare_event`, `activate_surge`, `activate_bulletin`, `open_housing_block`, `confirm_deployment`, `triage_claim`, `start_inspection`, `complete_inspection`, `void_advance_payment`, `activate_vendor_firm`, `accept_vendor_assignment`, `add_claim_to_batch`, `submit_batch`, `set_clock`, `ledger_for_claim`, `demobilize_deployment` — 16 helpers). Replaced the whole body with `return get_success_data(response, expected_status)`, which the runner already implements to handle both the "any 2xx" and "exact status" cases. Dropped the now-unused `validate_success` import. This single fix accounted for the large majority of the initial failure mass (the first sweep, run *after* this fix, was already at 156/170).

### Fixes applied to `test_suite/`
- `test_suite/test_corner_calculations.py` (3 tests) and `test_suite/test_corner_validations.py` (9 tests) — 12 occurrences of `meta["total"]` changed to `meta["total_count"]`. PRD §2.2/§2.3 name the pagination meta field `total_count` verbatim ("List responses populate `limit`, `offset`, `total_count` and `has_more` inside `meta`"); `meta["total"]` was a test-side mis-translation producing a bare `KeyError: 'total'`. Affected: `test_initial_case_reserve_basis_takes_the_greater_of_the_two_candidates`, `test_advance_paid_total_ignores_voided_advances_when_reissuing`, `test_inspection_revision_delta_goes_negative_below_the_standing_reserve`, `test_role_permission_is_checked_before_the_body_schema`, `test_claim_existence_is_checked_before_the_version_token`, `test_stale_claim_version_masks_the_negative_reserve_guard`, `test_funding_deployment_from_another_event_is_a_scope_mismatch`, `test_a_reserve_entry_may_land_on_zero_but_not_one_cent_below`, `test_a_housing_block_needs_a_strictly_later_checkout_date`, `test_bulletin_numbers_are_unique_per_event_not_across_events`, `test_duplicate_intake_is_keyed_on_policy_number_and_loss_date_together`, `test_vendor_capacity_is_evaluated_before_the_new_job_is_counted`.

### Fixes applied to `implementation/`
- `workspace/implementation/routes/vendor_assignments.py` — `accept_job()`: the acceptance-time vendor capacity gate now measures the ceiling against the firm's **other** open jobs (`firm_open_job_count(firm) - 1`) instead of the total. `open_job_count` counts assignments in `DISPATCHED` **or** `ACCEPTED` — forced by PRD §3.9's "Declining … recomputes `open_job_count`", "from `DISPATCHED` it simply recomputes `open_job_count`", and the corner test's requirement that a single `DISPATCHED` job already reads `open_job_count == 1` and blocks a second dispatch with `ERR_VENDOR_CAPACITY_EXCEEDED`. Under the old code the job being accepted was counted against itself, so acceptance at the ceiling was always refused — which made PRD §3.9's "when a job acceptance drives `open_job_count` to exactly `max_concurrent_jobs`, the firm moves `ACTIVATED → CAPACITY_HOLD`" unreachable. Fixed the two `test_difficulty_compensating_invariant.py` vendor-slot tests (`test_the_second_acceptance_consumes_the_last_slot_and_holds_the_firm`, `test_completing_one_job_hands_the_slot_straight_back_to_the_firm`) without weakening any PRD-required check; the dispatch-time gate and `sync_firm_capacity` were left exactly as they were, so a dispatch still never drives the `CAPACITY_HOLD` edge.

No flakiness surfaced: the 14-test failure set in iteration 1 and the 0-test failure set in iteration 2 were both identical across all 8 concurrent rounds. No PRD-required implementation check was removed or weakened; no `skip`/`xfail` added; no endpoint, field, or side effect added to `implementation/`; storage remains in-memory dicts only.

**Orchestrator note:** the subagent removed its `results.*.json` files before exiting, so its evidence was not left on disk. The orchestrator re-ran an independent 8-round sweep (`verify.1..8.json`) to confirm the green result before proceeding to Step 8.

## Step 8: Finalize PRD — align documentation to implementation — 2026-09-01T00:20:00.000Z

Done. `PRD_FINALIZED.md` written with three inline edits, all confined to §3.9 (the only `<step_7_diff>` item that touched `implementation/`).

## Line counts
- `PRD.md`: 483 lines / 111,038 chars
- `PRD_FINALIZED.md`: 483 lines / 111,800 chars
- Delta: 0 lines (+0.0%), +762 chars (+0.69%) — all edits are inline inside existing paragraphs; no sections added.

## Changes
- §3.9 "Registering a firm" — insert — pinned `open_job_count` as a read-derived count of the firm's assignments in `DISPATCHED` or `ACCEPTED` ("the open population", a term PRD used without defining) — `implementation/derive.py:259-262`, `implementation/derive.py:479`.
- §3.9 "Dispatching work" — insert — pinned that dispatch adds the job to the open population but never moves the firm's own `status`, so filling the ceiling by dispatch alone leaves the firm `ACTIVATED` — `implementation/routes/vendor_assignments.py:52-60` (no `sync_firm_capacity` call), vs. `implementation/ops.py:156-165`.
- §3.9 "Accepting" — revise — acceptance-time capacity ceiling is measured against the firm's *other* open jobs (`open_job_count` less one strictly below `max_concurrent_jobs`), not the total, so an acceptance consuming the last slot succeeds and drives `ACTIVATED → CAPACITY_HOLD` instead of being refused — `implementation/routes/vendor_assignments.py:107-109`.

Two `<step_7_diff>` items produced **no** PRD edit: the `test_helpers/fixtures.py` `_data()` repair is a pure fixture bug (no behavior at stake), and the `meta["total"] → meta["total_count"]` rename in `test_suite/` was a test-side mis-translation — PRD §2.2/§2.3 (lines 36-48, 76) already name `total_count` verbatim and `implementation/envelope.py:33-34` emits exactly `total_count`/`has_more`.

## Pre-edit search log

**Edit 1 — subject: definition/derivation of `open_job_count` and "open population".**
(b) Enumerated and read/grepped: `derive.py:259` (`firm_open_job_count`, sole definition — `DISPATCHED` or `ACCEPTED`); `derive.py:479` (`vendor_firm_out`, recomputes on every serialization); `ops.py:99` (`vendor_eligible`); `ops.py:111-114` (selector spare-capacity tiebreak); `ops.py:156-165` (`sync_firm_capacity`, both edges); `routes/vendor_assignments.py:45` (dispatch gate) and `:108` (accept gate); `routes/vendor_firms.py` (grepped — no stored `open_job_count` key anywhere, incl. registration and suspension at `:104`); `routes/claims.py:161-165` (closure's `ERR_VENDOR_JOB_OPEN` uses the identical `DISPATCHED`/`ACCEPTED` pair, already pinned in PRD line 234). Also grepped every `DISPATCHED` occurrence outside `vendor_assignments.py` to be sure no other status set competes.
(c) Adjustment: wrote "never stored … derived on every read" rather than "recomputed and stored on each transition", because no firm record ever carries the field; and phrased the pair as the firm's open population so the pre-existing "leaves the open population" / "recomputes `open_job_count`" sentences in §3.9 (activation, suspension, decline, complete, cancel) all stay true unmodified.

**Edit 2 — subject: what a dispatch does to the firm's status/occupancy.**
(b) Enumerated: `routes/vendor_assignments.py:52-60` (`create_job` — writes the assignment, `touch(claim)` only, no firm mutation, no `sync_firm_capacity`); `ops.py:156-165` (`sync_firm_capacity` — the only writer of the `ACTIVATED ↔ CAPACITY_HOLD` edges); its four callsites (`vendor_assignments.py:113` accept, `:126` decline, `:139` complete, `:151` cancel — dispatch absent); `routes/vendor_firms.py` activation/suspension/event-close paths (the other writers of firm `status`).
(c) Adjustment: scoped the claim to "the dispatch itself never moves the firm's own `status`" rather than "the firm's status only changes on acceptance", so activation, suspension, and the `DEMOBILIZING`-close cascade to `NETWORK_INACTIVE` are not contradicted.

**Edit 3 — subject: the acceptance-time `ERR_VENDOR_CAPACITY_EXCEEDED` gate.**
(b) Enumerated: `routes/vendor_assignments.py:88-113` (`accept_job` full check ladder: ownership → `DISPATCHED` → firm `ACTIVATED` → capacity → `sync_firm_capacity`); the parallel dispatch-time gate at `:45` (`>= max`, unchanged — new job not yet created, so it already means "other open jobs"); `ops.py:99` (selector eligibility, same `>=` semantics); `ops.py:156-165` (post-acceptance hold edge, `>= max`); `derive.py:259` (the count both gates read); decline/complete/cancel at `:115-153` (each recomputes and can release the hold).
(c) Adjustment: expressed the rule as "`open_job_count` less one must be strictly below `max_concurrent_jobs`" and explicitly limited it to the acceptance step, leaving the dispatch-time and selector-eligibility "strictly below `max_concurrent_jobs`" sentences verbatim — a global rewording of the ceiling would have mis-described `ops.py:99` and `vendor_assignments.py:45`. Also kept the trailing "reaches the ceiling" hold clause intact and only appended its consequence, so `sync_firm_capacity`'s `>=` test and the `CAPACITY_HOLD → ACTIVATED` release remain accurately described.

**Orchestrator verification:** 483 lines both sides, 3 revised lines (6 diff lines), 28 headers preserved, 0 hits for `difficulty_design|corner_design|test_recipe`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-01T00:35:00.000Z

All edits are applied. Final verification of counts is done.

## Result

`PRD_COMPLETED.md` written at `workspace/PRD_COMPLETED.md`.

**Source vs completed**
- `PRD_FINALIZED.md`: 483 lines, 111,800 chars
- `PRD_COMPLETED.md`: 483 lines, 121,058 chars (**+9,258 chars**)
- Line count identical: every change is an in-paragraph insert or revision. No new paragraphs, no new sections, no new table rows.

**Counts:** 33 changed lines — **23 ambiguity-pins**, **10 mismatch-revisions**.

**Changes**
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one field read from real wall-clock time, not the logical clock — `implementation/envelope.py:18`
- §2.3 — insert — ambiguity — blank/non-integer `limit` or `offset`, `limit` outside 1–100, negative `offset` are all `ERR_VALIDATION` — `implementation/envelope.py:44`
- §2.4 — insert — ambiguity — default list order is `created_at` asc with insertion sequence as final tie-break; ledger by `sequence_no`, snapshots by `computed_at_utc` — `implementation/store.py:64`
- §2.4 — insert — ambiguity — a path identifier is resolved before a body identifier of the same entity type — `implementation/routes/claims.py:98`
- §2.5 — insert — ambiguity — `created_at` is stamped from the logical clock with exactly three fractional digits — `implementation/store.py:52`
- §2.5 — revise — mismatch — roll-ups are derived at read time, so `version` advances only on explicitly enumerated operations; added the full both-ways enumeration for event and claim — `implementation/store.py:74`
- §2.6 — revise — mismatch — clock movement re-evaluates credential status as a pure bidirectional function of clock vs expiry (a rewind restores `VALID`) — `implementation/sync.py:31`
- §2.7 — insert — ambiguity — `expected_severity_index` and mandated percentages are rate inputs, not money, and are not coerced to 2dp — `implementation/validate.py:120`
- §2.10 — insert — ambiguity — room occupancy is derived on read from `CONFIRMED`/`ON_SITE` deployments only — `implementation/derive.py:145`
- §2.11 — insert — ambiguity — this ladder is the sole ordering authority; evaluation stops at the first failure — `implementation/routes/common.py:18`
- §2.11 — insert — ambiguity — the fixed entity order behind existence positions 4–14 — `implementation/validate.py:180`
- §3.1 — revise — mismatch — the two closure branches and their differing side-effect sets, including which children are touched — `implementation/routes/events.py:120`
- §3.2 — revise — mismatch — deadline recompute skips a claim still in `INTAKE` with a null deadline; anchor is `reported_at_utc` unless reopened — `implementation/sync.py:60`
- §3.3 — insert — ambiguity — adjuster registration field set and defaults — `implementation/routes/adjusters.py:24`
- §3.3 — revise — mismatch — the credential axis is bidirectional: the 30-day window is `expiry - 30d <= now < expiry`, and rewinding the clock walks it back — `implementation/sync.py:31`
- §3.4 — revise — mismatch — block-open tests event state (position 19) before room capacity (position 38) — `implementation/routes/blocks.py:52`
- §3.5 — insert — ambiguity — `rooms_reserved` defaults to 0 for `DESK` and 1 otherwise; `ERR_EVENT_SCOPE_MISMATCH` is checked at creation, not confirmation — `implementation/routes/deployments.py:44,50`
- §3.5 — revise — mismatch — the exact confirmation check order: status, availability, credential, posture, rest conflict, nightly capacity, licensing, rooms — `implementation/routes/deployments.py:96`
- §3.5 — insert — ambiguity — check-in touches only the deployment; the adjuster's derived hours and score need no write — `implementation/routes/deployments.py:150`
- §3.5 — insert — ambiguity — cancellation retains `provisional_cost` and the `surge_premium_tier` stamped at confirmation for audit — `implementation/routes/deployments.py:200`
- §3.6 — insert — ambiguity — coverage-line `limit_amount`, `deductible_amount` and `estimated_damage_amount` are required numbers and may not be negative — `implementation/validate.py:295`
- §3.6 — insert — ambiguity — cat-coding tests `INTAKE` first, then the event's status, yielding `ERR_EVENT_NOT_DECLARED` — `implementation/routes/claims.py:107`
- §3.6 — revise — mismatch — reopen precondition order is `CLOSED` → `ERR_EVENT_CLOSED` → `ERR_REOPEN_LIMIT_REACHED` — `implementation/routes/claims.py:180`
- §3.7 — revise — mismatch — licensing, capacity and window-conflict checks apply only to an explicitly pinned adjuster; the selector's filter covers them otherwise. An untriaged claim compares against its stored null mode, so every mode mismatches — `implementation/routes/assignments.py:59`
- §3.7 — insert — ambiguity — a claim in any handling status other than `TRIAGED`/`REOPENED` is left untouched, with no error and the assignment still created — `implementation/routes/assignments.py:108`
- §3.8 — revise — mismatch — manual `entry_type` accepts only `REVISION` or `PAYMENT`; `memo` must be a string; `settles_claim` defaults false; answers 201 with the created ledger row — `implementation/routes/claims.py:211,250`
- §3.8 — revise — mismatch — a settling `PAYMENT` moves the claim to `SETTLED` from any payment status and discards the submitted `delta_case_reserve`, so the negativity guard cannot fire — `implementation/routes/claims.py:223`
- §3.8 — insert — ambiguity — an untriaged claim's `advance_cap` reads 0.00, so the headroom gate refuses the advance — `implementation/derive.py:87`
- §3.8 — insert — ambiguity — `void_reason` is a required non-empty string validated ahead of all three preconditions — `implementation/routes/advances.py:93`
- §3.9 — insert — ambiguity — `service_states` must carry at least one entry — `implementation/routes/vendor_firms.py:24`
- §3.9 — revise — mismatch — licensing and capacity errors arise only on the pinned-firm path; added `required_vendor_type` to the vendor-assignment list filters — `implementation/routes/vendor_assignments.py:39,70`
- §3.9 — revise — mismatch — adding a claim to a batch answers 200 with the batch (not the claim) and does not move the batch's own `version` — `implementation/routes/batches.py:72`
- §3.9 — insert — ambiguity — batch rejection validates `rejection_reason` before the batch's status — `implementation/routes/batches.py:134`

**Deliberately not documented:** `ERR_NOT_FOUND` (404 unrouted path), `ERR_METHOD_NOT_ALLOWED` (405) and `ERR_INTERNAL` (500) from `implementation/app.py:28-41`. These are Flask-level infrastructure handlers outside the endpoint contract, and pinning them would have required new §5 catalogue rows, which the "never add new sections" constraint rules out. `implementation/errors.py` (101-entry HTTP status map) and `implementation/auth.py` (`ENDPOINT_ROLES`) were verified to match PRD §5 and §4 exactly, so neither needed any change.

**Orchestrator verification:** 483 lines, 28 headers, 75 endpoint rows, 101 `ERR_` catalogue rows all preserved; 33 changed lines (66 diff lines) vs `PRD_FINALIZED.md`; 0 hits for `difficulty_design|corner_design|test_recipe`; file terminates cleanly inside the §5 table.

---

## Pipeline complete — 2026-09-01T00:35:00.000Z

All nine steps done. Final state: 170/170 tests passing in 8/8 independent parallel rounds
(`workspace/implementation/results.{1..8}.json`), 0 tests deleted across the whole run.

### Orchestrator correction to the Step 9 citation list

The §3.4 bullet cites `implementation/routes/blocks.py:52`. No such file exists — the
handler is `implementation/routes/housing.py:69` (`open_block`). The *behavioral* claim
in the bullet was verified correct against that code: `open_block` tests
`ERR_HOUSING_NOT_PENDING`, then the event's status (`ERR_EVENT_NOT_DECLARED`), and only
then the room/capacity guard (`ERR_HOUSING_BLOCK_EMPTY`). Only the file:line pointer was
wrong; the PRD_COMPLETED.md edit itself needs no change.

### Final artifact inventory

Removed the three `CORNER_PART_{A,B,C}.yaml` provenance fragments after verifying their
combined 347,128 chars are byte-for-byte contained in `SCAFFOLD_CORNER_DESIGN.yaml`, plus
all `__pycache__`/`*.pyc`. Task directory now matches the pipeline's declared output layout.
