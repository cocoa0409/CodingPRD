# Worklog — task_1206_trade_secret_confidentiality_program

## Step 1: Create Task Directory — 2026-08-11T20:24:00.000Z

Pre-assigned output folder `tasks/task_1206_trade_secret_confidentiality_program` with `workspace/` subdirectory already exists; auto-index scan skipped per instructions. Step 1 recorded as done.

## Step 2: Generate Scaffold — 2026-08-11T21:18:00.000Z

All three scaffold artifacts are complete and lint-clean. Final summary:

## Task 1206 — Trade Secret & Confidentiality Program

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single top key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/SCAFFOLD_CORNER_DESIGN.yaml` (single top key `scaffold_corner_design`)

**Counts:**
- Entities: **16** (SecretAsset, ReasonableMeasure, Counterparty, NdaAgreement, NdaObligation, Employee, Acknowledgment, ExitInterview, AccessGrant, DisclosureRequest, ForensicReview, DemandLetter, PreservationNotice, EvidenceItem, TrainingAssignment, CleanDeskAudit)
- Endpoints: **74** · Error codes: **33** · Calculations: **7** · State machines: **16** · Validation priority tiers: **10** · OCC concurrency rules: **2** · Roles: **6**
- Difficulty-design instances: **22** (9 rules; dual-variant, non-linear-machine, cascade, and cross-entity each carry 3)
- Corner-design instances: **63** (57 active with full test recipes + 6 `excluded_because` stubs that all resolve to real difficulty instances)
- Lint: `VERDICT: clean lint` — 747 calls scanned, 0 violations; all FKs reverse-reachable; all numeric asserts pre-computed and machine-verified (score 64/55, damages 6500 vs 6501, risk 70/92.5/100, tiers at 30/60, dates 2026-07-15 / 2026-08-08 / 2026-05-31 / 2026-05-11)

**Design decisions worth noting:**
- **Archetype**: compliance/audit primary + workflow-orchestration secondary; **flat** entity topology, **cyclic** headline state shape (NDA breach loop, disclosure revision loop, grant suspend loop, measure lapse→re-verify, interview no-show reschedule), **segregation-of-duties** role model (measure implementer ≠ verifier, letter drafter ≠ approver, disclosure requester ≠ approver, own-ack signing).
- **Dual variants in three entity domains**: asset reasonable-measures score (operational vs documentary), counterparty exposure index (trailing-12m vs lifetime, only trailing drives risk_tier), disclosure risk (provisional vs final with tier multiplier + clamp).
- **Combinatorial formulas in two modes**: disclosure risk (mode a: 3-input multiplier + clamp + 80/95 routing branches), demand-letter damages (mode b: pinned per-line-then-sum rounding).
- **Two distinct interval semantics**: NDA closed-interval overlap (touching endpoints conflict, supersede carve-out via OCC-guarded `/amendments`) vs. department audit 7-day buffer gap semantics; exit interviews add half-open adjacency-allowed semantics in corner coverage.
- **OCC** on `SecretAsset.version` (PATCH) and superseded-NDA version (amendment create) — both true create/update races per the §1.2.1 filter.
- **Logical clock** `/_clock/set_current_utc` with the mandated 2026-05-01T00:00:00Z default, plus a `POST /api/program/sweep` ops-run checkpoint driving all six expiry/overdue classes in pinned order; policy starts at `v1`.
- Two correctness fixes made during self-review: NOTICE deliberately does not auto-revoke grants (keeps the zero-active-grants DEPARTED gate reachable), and publish supersedes only SIGNED acks so PENDING stale acks remain signable-attemptable → `ERR_POLICY_VERSION_STALE` stays reachable.

## Step 3: Copy Shared Files — 2026-08-11T21:19:30.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1206_trade_secret_confidentiality_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T21:42:30.000Z

The PRD is complete and verified. Summary below.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/workspace/PRD.md` — 362 lines, ends cleanly at §5 with no audit footer.

## Section list

- **§1 Introduction** (2 paragraphs — business-context angle: the "reasonable measures" legal standard, then system scope)
- **§2 Global Specifications** (12 subsections): 2.1 RBAC · 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by diff) · 2.3 Pagination · 2.4 Resource Identity and Common Properties · 2.5 The Program Clock and the Scheduled Sweep · 2.6 Optimistic Concurrency Control · 2.7 Reasonable-Measures Scoring and the Protection Posture · 2.8 Counterparty Exposure and Risk Tiering · 2.9 Segregation of Duties and Ownership Discipline · 2.10 Cascades, Ordering, and Referential Consistency · 2.11 Precision, Rounding, and Monetary Conventions · 2.12 Validation Priority
- **§3 Business Logic & Workflows** (9 subsections, entity-lifecycle grouping): 3.1 Asset register & measures · 3.2 Counterparties/NDAs/obligations · 3.3 Onboarding/acknowledgment/training · 3.4 Access provisioning · 3.5 Third-party disclosure · 3.6 Departure/exit interviews/forensic review · 3.7 Demand letters · 3.8 Preservation & evidence custody · 3.9 Clean-desk audits
- **§4 Endpoint Definitions** — 74-row table, 4 columns only (Method / Path / Description / Authorized Roles)
- **§5 Error Code Catalogue** — 33-row table, 2 columns only (Error ID / HTTP Status)

## Coverage audit (Zero-Silence Rule)

- **Contract 1 — Field-Name Coverage: PASS.** 115 unique required identifiers (131 entity-field entries + 178 endpoint input/query identifiers before dedup, plus `id`/`created_at`/`updated_at`/`version`) — all present in backticks, 0 missing. Verified by script against parsed SCAFFOLD.yaml (with fenced-code-block stripping to keep inline-token pairing intact).
- **Contract 2 — Rule Coverage: PASS.** All 15 state machines rendered with every transition's from/to pair, preconditions paired to error IDs, and side effects (including cascades: retire→abandon measures, bar→NDA-terminate→obligation-anchor→disclosure-reject, publish→supersede/re-issue, audit-conduct→lapse→posture→disclosure-return, EXECUTED→sealed MARKED_COPY evidence, LITIGATION→auto ISSUED PreservationNotice with `AUTO:`-prefixed `legal_matter_ref`). Both OCC rules expressed with write-operation + `expected_*_version` field + `ERR_STALE_VERSION`/412 and no race framing. All 7 calculations in precise reconstruction-grade prose (weights, multipliers, thresholds, the pinned per-line-rounding damages example 10,001→6,500-not-6,501, clamp, tier boundary inclusivity "exactly 30 is MEDIUM / exactly 60 is HIGH"). Validation priority stated as an explicit 10-category ordering. All 33 error IDs and all 100 enum/state values appear; all 6 roles named with identity-prose (4 opaque, 2 entity-backed). A 56-point scripted spot-check of load-bearing rules passed with zero failures.
- **Contract 3 — §3 Path Purity: PASS.** 699 backticked tokens in §3 scanned; 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos. All endpoints referenced via state-pair framing, role+verb, or capability description.

## Notable prose decisions

- **Clock/sweep lifted to §2.5** as a cross-cutting principle (fixed 6-class sweep order and strict-greater boundary semantics stated once), keeping §3 free of repetitive timing boilerplate.
- **Constants converted to natural units** per the skill's inference-difficulty guidance (365 days → "a year"/"trailing 365 days", 30-day windows → "thirty days", 7-day audit buffer, 90-day forensic window) while preserving exact boundary inclusivity.
- **Two intentional rule-density repairs** made after audit: `no_show_count` initial value (starts at zero) and training-assignment creation recomputing `training_current`.
- **OCC framed purely as stale-view rejection** ("advanced since the client last observed it") — no concurrency/race language.
- The `DRAFT`-vs-`ISSUED/ACTIVE` asymmetry between the asset-retire preservation block and the evidence-release block was preserved exactly as the scaffold's two state machines specify.

## Step 5: Generate Unit Tests — 2026-08-11T22:10:00.000Z

## Summary

Generated complete test infrastructure for `task_1206_trade_secret_confidentiality_program` purely from the four inputs (skill spec + SCAFFOLD + both design indices + PRD.md). No sibling tasks were touched.

### Helper files written (`test_helpers/`, 9 files)
- `types.py` — 16 entity TypedDicts (all `common_fields: true` → id/created_at/updated_at/version), all status/type enums, `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods)
- `api_errors.py` — `ApiErrorId` enum (33 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` + `assert_nda_obligation_bucket_invariant`
- `factories.py` — 16 payload factories, input fields only, unique-email-safe sequencing
- `constants.py` — measure weights, posture thresholds, exposure points/tier bounds, risk-score constants, claim factors, time windows, default clock/policy
- `test_users.py` — `TEST_USERS` shared constants + per-instance builders `make_employee_headers` / `make_counterparty_rep_headers` (entity-backed roles) and opaque-role id builders for SoD tests
- `fixtures.py` — composite fixtures: `create_registered_asset`, `create_active_nda` (CounterpartyRep ownership threading), `add_verified_measure` / `add_implemented_measure` (implementer≠verifier), `create_active_employee` (ack sign + activate + BASIC_TS), grant/disclosure lifecycle chains, `create_certified_interview`, `create_escalated_review_via_notice`, `make_obligations_overdue`, `escalate_obligations`, `create_counterparty_at_trailing`, `setup_adequate_asset`
- `__init__.py` — barrel export

### Tests emitted — 101 total, all design-index-tagged, zero untagged/dual-tagged

**Queue A (Difficulty): 44 tests over 22/22 instances (≥2 each)**
- dual_variant_calc: 6 (asset scores, counterparty trailing/lifetime, disclosure provisional/final)
- combinatorial_formula: 4 (tier-multiplier clamp → `ERR_DISCLOSURE_RISK_TOO_HIGH`; per-line rounding 6500≠6501)
- non_linear_state_machine: 6 (breach loop, return-revision loop, grant suspend loop)
- transitive_cascade: 6 (audit→lapse→posture→RETURNED; publish supersede/reissue; bar→terminate→anchor)
- priority_pair_validation_conflict: 4 (state>safety, safety>temporal — PRD §2.12 "lower numbers win" covers priority verbatim)
- boundary_precision_check: 4 (posture exactly-70; zero-active-grants departure)
- cross_entity_state_dependency: 6 (NDA-not-active, ack-required, preservation-hold)
- resource_temporal_overlap: 4 (NDA closed-interval touch; audit 7-day buffer)
- compensating_invariant: 4 (grant count conservation; obligation bucket conservation)

**Queue B (Corner): 57 tests over 57/57 non-stub instances** — entities 9, state_machines 12, calculations 4, validations 10, endpoints 3, errors 6, rbac 8, cross_cutting_layers 4, consistency_model 1.

**Instances skipped: 0** (no PRD-first filter failures). **Stubs not translated: 6** (`excluded_because:` — all cross-references verified to resolve to real difficulty instances; the owning queue-A tests carry those assertions).

### Verification
- `python3 -m py_compile`: all 29 files pass
- Every test module imports cleanly with `test_helpers` on the path
- Tag audit: 0 unresolved tags, 0 tests with ≠1 `Design:` line, all queue-A instances ≥2 tests, all non-stub queue-B instances ≥1
- Citation audit: a distinctive ≥8-word substring from every test's PRD citation survives literal grep of `workspace/PRD.md` (101/101)

## Step 6: Generate Implementation — 2026-08-11T22:10:30.000Z

Done. Summary below.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/workspace/implementation/`:

| File | Contents |
|---|---|
| `start.sh` | Guarded launcher: no-op `pip install` unless flask missing, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT`, default 10000) |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask app factory, blueprint registration, ApiError/404/405/exception handlers → envelope, `/health` probe |
| `db.py` | In-memory stores (16 dicts, start empty), logical clock (initial `2026-05-01T00:00:00Z`), program state (`v1`), ISO-8601 3-fractional-digit formatting, second-precision parsing, calendar-month arithmetic, `new_record`/`touch` (version starts at 1, +1 per direct mutation) |
| `errors.py` | `ApiError` + all 33 scaffold error IDs with exact HTTP statuses |
| `response.py` | Exact envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp`, `response_type` object/array/error, `data.error_id/message`; list `meta` gains `limit/offset/total_count/has_more` (defaults 10/0, clamp 1–100) |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (6 declared roles → 401), endpoint role gates (403), body/field/enum/int helpers |
| `services.py` | All §1.3 calculations in `Decimal` (measure weights/posture thresholds, exposure indexes with 365-day window + 100 cap + tier boundaries 30/60, disclosure risk provisional/final with tier multiplier + clamp 0–100 + 80/95 routing, per-line round-half-up damages — verified the pinned 10001→6500 example), plus cascades (bar→terminate+anchor+reject, lapse→DEFICIENT→RETURNED, retire→abandon, terminate/expiry anchoring) |
| `routes_program.py` | clock set, program status (per-entity status counts), policy publish (supersede SIGNED created_at-ASC, re-issue PENDING), sweep (fixed 6-class order, strict `>` comparisons) |
| `routes_assets.py` | assets CRUD + OCC PATCH (`expected_asset_version` → 412), state machine, posture-report; measures with implementer≠verifier SoD and evidence gate |
| `routes_nda.py` | counterparties (+bar cascade), NDAs (closed-interval overlap incl. touching dates, amendment OCC `expected_superseded_nda_version` + parent version bump, supersede-on-activation, terminate/expiry anchoring), obligations (CounterpartyRep ownership on fulfill) |
| `routes_people.py` | employees (onboard cascade: ack + BASIC_TS due hired+30d, email uniqueness, departure triple-gate), acknowledgments (own-sign, policy-staleness), exit interviews (half-open overlap, no-show loop, 2-no-show escalate, dual-flag certify), training (own-complete, currency recompute) |
| `routes_access.py` | grants (clearance↔classification need-to-know 403, expiry > now & ≤ now+365d, CROWN_JEWEL→IPCounsel gate, requester≠approver, compensating count), disclosures (version pinning, provisional/final risk, endorsement routing, stale-reference 409, EXECUTED→sealed MARKED_COPY evidence) |
| `routes_legal.py` | forensic reviews (90-day post-departure window, evidence-before-findings, counsel loop, ≥1 indicator to escalate), demand letters (ESCALATED-only, drafter≠approver, ISSUED deadline, LITIGATION→auto `AUTO:<id>` ISSUED notice), preservation notices (issue non-empty scope, release blocked by LITIGATION letters), evidence (64-hex hash 422, release blocked by ISSUED/ACTIVE hold) |
| `routes_audits.py` | clean-desk audits (7-day departmental buffer, conduct findings arithmetic + linked-measure lapse cascade, remediate/close gates) |

## Verification results

- **Route parity: MATCH — 74/74.** Scripted comparison of `(method, path)` pairs extracted from SCAFFOLD.yaml `endpoints:` vs Flask `url_map` (placeholders normalized): 0 missing, 0 extra under `/api`. Only extras are `GET /health` (readiness probe) and Flask's built-in `/static`.
- **Smoke test:** `bash start.sh` boots cleanly on an exported PORT in ~1.5s; `/health` 200; fresh boot confirmed empty store (`total_count: 0`, policy `v1`, clock `2026-05-01T00:00:00Z`); create/list flow works (counterparty 201 → list total 1); unauthenticated → `ERR_UNAUTHENTICATED` envelope; server killed cleanly afterward.
- **Functional e2e (two scenario scripts, ~90 assertions, all passing):** onboarding→ack→activation, training currency + 365-day decay, measure scoring (15.0/20/35→45, DEFICIENT→ADEQUATE→STRONG), grant lifecycle incl. CROWN_JEWEL role gate and `ERR_NEED_TO_KNOW_VIOLATION`/`ERR_EXPIRY_IN_PAST` (exactly +365d accepted), NDA overlap/closed-interval, amendment OCC 412 + parent version bump + SUPERSEDED cascade, strict sweep boundaries (at-expiry stays ACTIVE, +1s expires), RETURN_OR_DESTROY anchoring at terminated_at/expiry+30d, exposure points (OVERDUE 10 → ESCALATED 25, status-exclusive), disclosure pins + `ERR_STALE_REFERENCE` after asset PATCH, endorsement ≥80 / forbidden ≥95 with clamp, EXECUTED sealing MARKED_COPY, damages 6500 per-line rounding, interview no-show/escalate/certify, departure triple-gate, 90-day review window (boundary inclusive), audit buffer (exactly 7 days apart allowed), lapse→DEFICIENT→RETURNED cascade, bar cascade (terminate NDAs + reject DRAFT/SUBMITTED/UNDER_REVIEW disclosures), publish supersede/re-issue, ack expiry, employee own-record read 403.

## Notable design decisions

- **Logical clock everywhere**: `created_at`/`updated_at` and all transition stamps use the logical clock (not wall-clock) so deadline rules compose deterministically; the clock read/set path echoes the raw string (`2026-05-01T00:00:00Z` initial verbatim) while entity timestamps use the mandated 3-fractional-digit form.
- **Derived fields recomputed eagerly without version bumps**: only direct mutations (PATCH, state transitions, explicit stamps, the two OCC writes) increment `version` — otherwise any measure/obligation activity would falsely stale disclosure pins (the pin is the §3.5 serialization point for descriptive edits and amendments only).
- **Validation precedence follows PRD §2.12 categories** (auth→role→ownership/SoD→existence→OCC→state→safety→temporal→referenced-state→constraints), which deliberately reorders some scaffold per-transition precondition lists (e.g., SoD before state gates at disclosure approval; classification-ceiling before NDA-active at review).
- **Boundary semantics**: all sweep comparisons strict `>`; inclusive 365-day windows for exposure/training; grant provisioning allowed at exactly `expires_at`; execution allowed up to exactly `planned_disclosure_date + 30d`; review window inclusive at exactly departed+90d; half-open interview overlap; closed-interval NDA overlap with touching dates counting.
- **No seeding**: the store starts empty; every entity is built through the declared API surface.

## Step 7: Run Tests and Iterate — 2026-08-11T22:30:00.000Z

All 8 rounds pass 101/101. The loop exits cleanly.

## Summary

**Iterations run:** 2 sweeps (8 parallel rounds each).
- Sweep 1: 96/101 in all 8 rounds — 5 distinct failures, all deterministic (8/8 rounds), zero flaky tests.
- Sweep 2: 101/101 in all 8 rounds — clean.

**Tests deleted:** none.

**Failures diagnosed (union across rounds) and resolutions:**

1. **Stamped/computed datetime string format not uniquely derivable (4 tests, STEP 1b → 1c partial-coverage split).** The tests asserted exact strings like `"2026-07-15T00:00:00Z"` for `terminated_at`, `due_at`, `confidentiality_end`, and `sealed_at`. PRD mandates the three-fractional-digit form verbatim only for `api_request_timestamp` (§2.1), `created_at`/`updated_at` (§2.4), and pins the clock echo verbatim (§2.7); for all other datetimes §1.3 states only "Datetimes are compared and stored at second precision." A faithful PRD-only reader can render stamped fields either as `...T00:00:00Z` or `...T00:00:00.000Z` (the implementation chose the latter uniformly). The date *arithmetic* the tests assert (terminated_at + 30 days; created_at + 10 days; hired_at + 30 days; expiry + survival_months; sealed_at = current clock) IS verbatim PRD, so per STEP 1c the covered assertion was kept and the uncovered format assertion removed: comparisons now go through a new `assert_same_instant` helper that parses both sides to instants. No implementation change — the existing behavior is one of two PRD-admissible readings.

2. **Evidence-seal setup violated a PRD precondition (1 test, STEP 2 fixture bug).** `test_evidence_seal_stamps_sealed_at_and_stores_hash_verbatim` opened a manual forensic review for a `PREBOARDING` employee; PRD §3.6 allows manual opening only "while the employee is `ACTIVE` or `NOTICE`, or after departure within a ninety-day window," so the implementation's 409 `ERR_INVALID_STATE` was correct. The test's setup, not the implementation, was at fault.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/test_helpers/assertions.py` — added `assert_same_instant(actual, expected, label)`: instant-equality comparison for stamped/computed datetimes, with a docstring citing the PRD coverage boundary (value pinned by §1.3; string form pinned only for `api_request_timestamp`/`created_at`/`updated_at`).

**Fixes applied to `test_suite/`:**
- `test_06_transitive_cascades.py` — `test_bar_terminates_nda_and_anchors_return_obligation`: `terminated_at` and anchored `due_at` assertions now use `assert_same_instant`.
- `test_11_entity_creation_and_defaults.py` — `test_employee_create_auto_seeds_ack_and_training`: ack `due_at` (+10d) and training `due_at` (+30d) now instant-compared; `test_evidence_seal_stamps_sealed_at_and_stores_hash_verbatim`: setup switched from `create_employee_record` to `create_active_employee(complete_training=False, ...)` so the PRD §3.6 review-opening gate is satisfied, and `sealed_at` now instant-compared.
- `test_12_lifecycle_transitions.py` — `test_nda_full_happy_path`: `confidentiality_end` now instant-compared.
- `test_18_occ_version_pinning_and_cascades.py` — `test_cascaded_execute_creates_sealed_marked_copy`: `sealed_at` now instant-compared.

**Fixes applied to `implementation/`:** none — every failure traced to the test artifact layer; the implementation was PRD-faithful in all 5 cases.

**Feedback notes for generators (no deletions, but two near-miss patterns):**
- unit-test-generator: exact-string equality on datetime fields whose string form PRD does not pin (only `api_request_timestamp`/`created_at`/`updated_at` are 3-fraction-mandated; §1.3 second-precision covers the rest) — generated assertions should compare instants for stamped/computed datetimes.
- unit-test-generator: fixture for evidence-seal flow omitted the PRD §3.6 employee-state precondition (must be ACTIVE/NOTICE/recently DEPARTED before a manual review can be opened).

## Step 8: Finalize PRD — 2026-08-11T22:34:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/workspace/PRD_FINALIZED.md` written with exactly one inline addition.

**Summary on exit**

- **Line counts:** PRD.md = 362 lines, PRD_FINALIZED.md = 362 lines (0% line-count delta; the change extends the existing line 129 in place, no lines added or removed).

- **Changes (one bullet per change):**
  - **§2.11 (Precision, Rounding, and Monetary Conventions) — revise —** appended one sentence pinning that datetime fields the server stamps at the current clock or computes (e.g. `terminated_at`, `sealed_at`, `issued_at`, `signed_at`, `completed_at`, `fulfilled_at`, `escalated_at`, `notice_given_at`, `departed_at`, `conducted_at`, anchored/auto-assigned `due_at`, `response_deadline`, `confidentiality_end`) are rendered as ISO 8601 UTC with exactly three fractional digits, the same form as `created_at`/`updated_at` (§2.4) — this resolves Step-7 item 1 (the only genuine PRD silence found). **Impl evidence:** `implementation/db.py:71-73` (`fmt_ts`, the sole renderer), `db.py:140-144` (`stamp`), `services.py:241,254`, `routes_nda.py:214,265,445,467`, `routes_people.py:104,116,181,219,244,286,405,527`, `routes_access.py:473`, `routes_legal.py:320-325,558`, `routes_program.py:140`.

- **Step-7 item 2 (evidence-seal fixture bug):** no PRD edit. Verified the implementation (`implementation/routes_legal.py:89-94`) enforces exactly what PRD §3.6 line 213 already pins: manual review opening requires `ACTIVE`/`NOTICE` (else `ERR_INVALID_STATE`) or `DEPARTED` within 90 days (else `ERR_REVIEW_WINDOW_EXPIRED`). PRD fully determines the behavior; the failure was test-side only.

- **Per-edit pre-edit search log:**
  - (a) **Subject:** string rendering form of server-stamped/computed datetime fields.
  - (b) **Impl paths enumerated:** `db.py:71-73,114-144,147-151` (renderer, stamp/touch, serialize pass-through); `response.py:19` (`api_request_timestamp`); all `stamp()` callsites (`routes_nda.py:445,467`; `routes_access.py:473`; `routes_people.py:181,219,286,405,527`; `services.py:254`; `routes_legal.py:320,558`); all computed-field sites (`services.py:241`; `routes_program.py:140`; `routes_legal.py:324`; `routes_nda.py:214,265`; `routes_people.py:104,116,244`); all client-supplied verbatim-echo sites (`routes_nda.py:206-207,257-258,383`; `routes_people.py:87,333-334,425-426,477`; `routes_access.py:127,265`; `routes_audits.py:62-63`); clock echo (`routes_program.py:88-89,106`; `db.py:47-50,61-63`). Grep confirmed `fmt_ts` is the only datetime formatter in the codebase (single `strftime` at db.py:73; only `fromisoformat` for parsing).
  - (c) **Wording adjustment:** scoped to fields "the server stamps at the current clock or computes" so the sentence does not claim the clock echo `now_iso8601` (verbatim client string, already pinned as "echoed" in §2.5) or client-supplied datetime fields (stored verbatim per the `raw if isinstance(raw, str) else fmt_ts(dt)` pattern everywhere); used a non-exhaustive "for example" field list and qualified `due_at` as "anchored or auto-assigned" so client-supplied `due_at` values (stored verbatim at `routes_nda.py:383`, `routes_people.py:477`) are not mis-described.

## Step 9: Complete PRD — 2026-08-11T22:51:00.000Z

All edits are applied and verified. The file is at `/home/ubuntu/github/CodingPRD/tasks/task_1206_trade_secret_confidentiality_program/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs. output:** PRD_FINALIZED.md = 362 lines / 62,430 bytes; PRD_COMPLETED.md = 363 lines / 67,619 bytes (+1 line, +5,132 chars). All changes are in-paragraph inserts/revisions — no new sections, no deleted requirements.

**Counts:** 29 ambiguity-pins, 7 mismatch-revisions (36 changes total; two mismatches are pinned in paired locations §2.10↔§3.9).

**Changes (section — insert/revise — kind — what changed — impl ref):**

- §2.1 — revise — ambiguity — Employee may GET only their own employee record (`ERR_OWNERSHIP_REQUIRED` otherwise); list endpoints apply no ownership scoping — routes_people.py:140-142; all list handlers.
- §2.2 — revise — ambiguity — `api_request_timestamp` reads the logical clock, not wall clock — response.py:16-20.
- §2.2 — insert — ambiguity — undefined path/method → `ERR_NOT_FOUND` 404; non-object JSON body → `ERR_INVALID_REQUEST`; unparseable body treated as `{}` — app.py:34-51; middleware.py:48-54.
- §2.3 — revise — ambiguity — out-of-range `limit`/`offset` clamped, unparseable falls back to defaults (never an error) — response.py:47-69.
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order; `has_more` = offset + page size < total_count — db.py:162-165; response.py:33.
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — db.py:114-129.
- §2.5 — revise — ambiguity — clock echoes the submitted string verbatim, unparseable `to_iso8601` → `ERR_INVALID_REQUEST`, all server timestamps read the logical clock, `counts` keyed by entity type name → status → row count — routes_program.py:79-109; db.py:56-68.
- §2.8 — revise — ambiguity — disclosure "execution time" is the `updated_at` of the terminal EXECUTED transition — services.py:135-140.
- §2.8 — revise — ambiguity — lifetime exposure index is capped at 100 too (PRD pinned the cap only for trailing) — services.py:141-142.
- §2.8 — revise — **mismatch** — recompute triggers: waiver and counterparty suspend/reactivate do NOT recompute; barring and single-counterparty reads do (PRD said "waiver… counterparty state changes… as part of the sweep") — routes_nda.py:113-115,130-146,452-460; services.py:249-286.
- §2.10 — revise — ambiguity — derived-field recompute never bumps parent `version`; GET-by-id of counterparty/NDA/employee and the posture report reconcile before responding; list endpoints do not — services.py:1-9; routes_nda.py:114,291; routes_people.py:143; routes_assets.py:207.
- §2.10 — revise — **mismatch** — exception to every-identifier-must-resolve: audit `linked_measure_ids` unresolvable entries ignored — routes_audits.py:136-142.
- §2.11 — revise — ambiguity — calendar-month addition day-clamps (Jan 31 + 1mo → Feb 28/29); client-supplied datetimes stored/returned exactly as submitted — db.py:93-99; routes_nda.py:206-207 et al.
- §3.1 — revise — ambiguity — posture-report shape: key is `asset_id`; `measures` array in created_at order carrying id/measure_type/title/status/weight_points/points_effective — routes_assets.py:200-227.
- §3.1 — revise — ambiguity — measure creation is not gated on asset status — routes_assets.py:233-258.
- §3.1 — revise — ambiguity — abandonment (like verification and lapsing) is an IPCounsel-only transition — routes_assets.py:312-333.
- §3.2 — revise — ambiguity — NDA termination is IPCounsel's step — routes_nda.py:344-349.
- §3.2 — revise — ambiguity — supplying `due_at` for RETURN_OR_DESTROY → `ERR_INVALID_REQUEST`; `counterparty_id` obligation filter joins through the parent NDA — routes_nda.py:374-377,400-408.
- §3.3 — revise — ambiguity — manual acknowledgment issuance requires only that the employee exist (not conditioned on a lapsed ack or employee status) — routes_people.py:229-250.
- §3.3 — revise — ambiguity — training-currency 365-day window is closed, inclusive at both ends — services.py:186-203.
- §3.4 — revise — ambiguity — `training_current` is recomputed at the moment of grant approval — routes_access.py:183-186.
- §3.5 — revise — ambiguity — disclosure creation requires the governing NDA's counterparty to be ACTIVE, else `ERR_COUNTERPARTY_NOT_ACTIVE` — routes_access.py:247-250.
- §3.5 — revise — ambiguity — submission re-requires the asset to still be REGISTERED — routes_access.py:342-343.
- §3.5 — revise — ambiguity — execution is IPCounsel's step; the sealed marked copy carries `byte_size` zero — routes_access.py:440-473.
- §3.6 — revise — **mismatch** — interview flags settable any time before a terminal state (PRD said "between conducting and certifying"; impl allows SCHEDULED/NO_SHOW/ESCALATED too) — routes_people.py:365-385.
- §3.6 — revise — **mismatch** — `ESCALATED` added to terminal interview states (PRD pinned only CERTIFIED/CANCELLED; impl defines no outgoing transitions from ESCALATED) — routes_people.py:388-452.
- §3.6 — revise — ambiguity — `exfil_indicator_count` is a non-negative integer — routes_legal.py:139-143.
- §3.7 — revise — **mismatch** — drafting validates `claim_lines` (including asset existence) before checking the review's ESCALATED status, `response_deadline_days` last — deviates from §2.12's strict category order — routes_legal.py:230-252.
- §3.7 — revise — ambiguity — the same asset may appear on multiple claim lines, each contributing its own rounded amount — services.py:174-180.
- §3.7 — revise — ambiguity — recipient acknowledgment (`ISSUED → ACKNOWLEDGED`), compliance, and withdrawal are IPCounsel steps (PRD said only "counsel"; endpoint also admits SeniorCounsel) — routes_legal.py:327-340,363-369.
- §3.7 — revise — ambiguity — AUTO preservation notice `asset_ids` de-duplicated in claim-line order — routes_legal.py:348-362.
- §3.8 — revise — ambiguity — notice issue and activation are IPCounsel steps — routes_legal.py:449-464.
- §3.8 — revise — **mismatch** — evidence-release hold consults only the item's own `review_id`; PRD's "disclosure_id chains to a covered review" block removed (no such link exists; marked copies are never hold-blocked) — routes_legal.py:560-570.
- §3.9 — revise — ambiguity — seven-day audit buffer math: conflict unless each window starts ≥7 days after the other ends; exactly 7 days permitted — routes_audits.py:49-57.
- §3.9 — revise — **mismatch** — `linked_measure_ids` optional, defaults to empty, unresolvable ids silently ignored (vs §2.10's blanket must-resolve rule) — routes_audits.py:132-144.
- §4 — revise — ambiguity — `to_status` outside the entity's vocabulary → `ERR_INVALID_REQUEST`; a defined status with no transition from current state → `ERR_INVALID_STATE` — e.g. routes_assets.py:157-159.

**Notable findings:** the two genuine behavioral mismatches with observable consequences were (a) §2.8's recompute-trigger list (impl stores stale indexes after waivers/suspends until a trigger or single-read reconciles) and (b) §3.8's disclosure-chained evidence block (unimplementable — disclosures carry no review link — and absent from impl). Everything else was PRD silence around actor identity for per-transition role gates, validation orderings, boundary inclusivity, echo/serialization conventions, and lazy-read reconciliation.
