# Worklog — task_1302_neighborhood_pet_sitting_cooperative

## Step 1: Create Task Directory — 2026-08-12T19:24:00.000Z

Task directory `tasks/task_1302_neighborhood_pet_sitting_cooperative/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 3: Copy Shared Files — 2026-08-12T19:25:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1302_neighborhood_pet_sitting_cooperative/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-12T20:10:00.000Z

RESUME RUN note: previous terminated run left a complete, valid `SCAFFOLD.yaml` (1631 lines; §1.0–§1.7: 12 entities, 8 state machines, 8 calculations, 19 validations, 58 endpoints, 25 errors, 3 roles; complexity profile = ledger_reconciliation + posture_driven_gating with optimistic_concurrency / cascading_side_effects / dual_variant_calculation / rate_threshold_triggers) but no design-index files. Step 2 resumed by generating ONLY §1.8/§1.9 against the existing SCAFFOLD.yaml. Subagent summary (verbatim):

Both design indices are complete and verified. Summary of what was produced and found:

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2458 lines, single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/SCAFFOLD_CORNER_DESIGN.yaml` — 3538 lines, single top-level key `scaffold_corner_design`
- `SCAFFOLD.yaml` was read but never modified.

## §1.8 instance counts per rule_id (28 total, ≥2 minimum met everywhere)

`dual_variant_calc` 2 · `combinatorial_formula` 3 · `non_linear_state_machine` 3 · `transitive_cascade` 3 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 4 · `cross_entity_state_dependency` 4 · `resource_temporal_overlap` 3 · `compensating_invariant` 3

## §1.9 instance counts per section (86 entries: 70 full recipes + 16 excluded_because stubs)

entities 11 · state_machines 16+2 stubs · calculations 6+2 stubs · validations 19 · endpoints 10 · errors 9 stubs · rbac 4 · cross_cutting_complexity_layers 2+3 stubs · consistency_model 2

## Difficulty tiers selected (hardest options throughout)

- Rule 2 exercised in all three modes: (a) max-over-intersecting-windows with disabled-window exclusion, (b) nested rounding where round-at-posting vs round-at-end diverge (0.85 vs 0.84, verified by execution), (c) incident-penalty↔settle circular-looking ordering.
- Boundary probes hug exact edges: early_fraction 0.25 exactly vs 0.25417 (settled 4.00 vs 1.49), overdraft margin exactly −5.00 vs −5.50, late-cancel at exactly 24.0h vs 23h, 365-day incident window inclusive edge, half-open adjacency (14:00 touch passes, 13:59 overlap fails), closed buffered entry window at ±1 second.
- Every numeric assert was precomputed by code; all 40+ character-length literals (20/19/30/29/39-char bounds) were machine-verified.

## Verification results

- Both files parse as YAML; 114 instance names unique across the union; all `grounds:` references resolve against SCAFFOLD.yaml (calculations, transitions, validations by priority, entity fields, errors, concurrency rule, endpoints, roles — checked programmatically); all 16 `excluded_because` stubs cite existing §1.8 instances; placeholder closure clean (every `${var}` bound by an earlier `captures:`); logical clock is monotonic within every instance; every request's `start_at` is after the clock value at posting time.
- `scaffold_lint.py`: 2821 calls scanned, **zero violations of checks (a)–(e)**. The 21 remaining violations are all rule (f) `FK_REVERSE_UNREACHABLE` — I proved they are pre-existing by linting SCAFFOLD.yaml with empty design files (same 21). They stem from the frozen scaffold (linter expects literal `{id}` path placeholders vs the scaffold's `{memberId}` style, plus a few genuinely absent reverse GETs) and cannot be fixed without modifying SCAFFOLD.yaml, which was forbidden.

## Deliberate omissions / pinned interpretations (documented in both file headers)

1. **Vetting bootstrap tension (pinned reading)**: §1.2 requires reference referees to be VETTED and requires reciprocal rows (applicant-as-referee) ACCEPTED before finalize — so no first VETTED member is reachable from empty-DB under the strictest letter. All chains adopt the documented mutual-vouch reading: a 3-member founding clique accepts all six mutual references; later applicants use VETTED referees for primary rows with reciprocal rows accepted as mutual confirmations. `ERR_REFEREE_NOT_VETTED` is still tested via a SUSPENDED referee, which replays cleanly under any reading.
2. **ERR_NO_CHECKIN omitted**: unreachable under the declared surface (checkout requires IN_PROGRESS, which itself requires a prior CHECK_IN). Documented in the corner file header rather than papered over with a broken chain.
3. No sibling task directories were inspected at any point.

## Step 4: Generate PRD — 2026-08-12T20:25:00.000Z

Subagent summary (verbatim):

All three hard contracts pass. The earlier failures were an extraction artifact (fenced JSON blocks misaligned naive backtick pairing); with fences stripped, everything is covered. PRD is written at `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/workspace/PRD.md`.

## Summary

**PRD line count:** 294 lines (~40 KB)

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 Membership Roles and Caller Identity · 2.2 API Response Structure (verbatim fixed block, confirmed byte-identical) · 2.3 Pagination and List Filtering · 2.4 The Hours Ledger · 2.5 Reliability Standing · 2.6 Logical Time and Time-Driven Cascades · 2.7 Request Evaluation Order · 2.8 Nested Resource Resolution · 2.9 Common Resource Properties · 2.10 Hour Arithmetic and Rounding · 2.11 Optimistic Concurrency on Claim Acceptance
- §3 Business Logic & Workflows: 3.1 Joining/Vouching/Vetting · 3.2 Pet Profiles · 3.3 Holiday Demand & Posting · 3.4 Claiming & Assignment Formation · 3.5 Keys/Access/Entry Log · 3.6 Completion/Settlement/Ledger · 3.7 Incidents/Disputes/Removal
- §4 Endpoint Definitions (58-row, 4-column table — exact match to scaffold, no missing/extra)
- §5 Error Code Catalogue (25-row, 2-column table)

**Hard contract reports (all PASS):**
- Contract 1 Field-Name Coverage: entity fields 75/75, endpoint inputs 48/48, query params 11/11, common fields 4/4 — 0 missing. Enums/states 62/62 present.
- Contract 2 Rule Coverage: 19 validations expressed with priority rendered as an explicit 19-step ordered pipeline in §2.7 (plus local reiteration at claim acceptance in §3.4); 1 OCC rule expressed with endpoint framing, `expected_sitting_request_version`, `ERR_STALE_VERSION`/412 (§2.11 + §3.4); 35 state-machine transitions expressed with preconditions and side effects (§3.1–3.7); 7 calculations expressed in precise prose (holiday-max pricing, provisional-vs-final settlement with the strictly-greater-25% early-departure boundary, event-wise reliability with clamp, chronological ledger replay with `id` tiebreak, half-open overlap with adjacent-interval exclusion, 24h late-cancel with "exactly 24 is not late", 0.5 incident penalty, 2-in-365-days-inclusive removal); all endpoint side effects and applies_to scopes rendered; EntryLog/CreditLedgerEntry called out as carrying only `id` + `created_at`.
- Contract 3 §3 Path Purity: 312 backticked tokens scanned in §3, 0 path/method violations.

**Zero-silence coverage map (scaffold → PRD):** entities → §2.9 + §3.1–3.7 narratives; Member machine → §3.1; MemberReference machine → §3.1; SittingRequest/SittingClaim machines → §3.3–3.4; SittingAssignment machine → §3.4–3.6 (+DISPUTED in §3.7); AccessHandoff machine → §3.5; Incident/Dispute machines → §3.7; calculations → §2.4/2.5/2.10 + §3.3/3.4/3.6/3.7; validations 1–19 → §2.7 pipeline with per-rule prose at the guarded workflow; concurrency rule → §2.11/§3.4; response envelope → §2.2 verbatim; pagination → §2.3; roles + identity → §2.1; clock endpoint → §2.6; errors → §5 plus trigger prose throughout §2/§3.

**Rules not renderable in prose:** none — every scaffold rule was expressed.

## Step 5: Generate Unit Tests — 2026-08-12T21:15:00.000Z

Subagent summary (verbatim):

Generation complete. Final summary:

## Summary

**Task**: task_1302_neighborhood_pet_sitting_cooperative — generated `test_helpers/` (9 files) and `test_suite/` (8 files), 126 test functions total, all collecting cleanly under pytest.

### Tests emitted per queue

- **Queue A (Difficulty)**: 28/28 instances covered, each with ≥2 tests (56+ test functions tagged `Design: Difficulty/<rule_id>/<name>`).
- **Queue B (Corner)**: 70/70 non-stub instances covered, each with ≥1 test (70 tagged `Design: Corner/<section>/<name>`).

### Per design section (Queue B)

- `entities`: 11/11 — `state_machines`: 16 non-stub of 18 (2 stubs) — `calculations`: 6 non-stub of 8 (2 stubs) — `validations`: 19/19 — `endpoints`: 10/10 — `errors`: 0 non-stub (9 stubs) — `rbac`: 4/4 — `cross_cutting_complexity_layers`: 2 non-stub of 5 (3 stubs) — `consistency_model`: 2/2.

### Instances skipped with PRD-filter reasons

Zero instances were skipped on PRD-filter grounds. All 16 `excluded_because:` stubs were honored (not translated); every stub's `difficulty_instance` cross-reference was verified to resolve to a real §1.8 instance name. No `pytest.mark.skip`/`xfail`/`skipif` anywhere in the suite.

Notable adjudications: the founders' mutual-vouch bootstrap (three APPLIED members vouching in a clique, per the design indices' pinned reading) is implemented in `fixtures.bootstrap_founders()`; all PRD citations were verified to survive literal grep (157 quoted rule-bearing passages, all matched after whitespace normalization); `ERR_NO_CHECKIN` correctly has no test (the corner index itself documents it as unreachable).

### test_helpers/ file list

`__init__.py`, `types.py`, `api_client.py` (one method per PRD endpoint), `api_errors.py` (25 error IDs, HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (with `make_member_headers` per-instance builder for the entity-backed Member role), `fixtures.py` (bootstrap/vetting/pet/request/claim/accept/in-progress/completed/settled composite chains, dispute/incident helpers).

### test_suite/ file list

`conftest.py`, `test_01_membership_and_vetting.py` (18 tests), `test_02_pet_profiles_and_holiday_windows.py` (10), `test_03_sitting_requests_and_claims.py` (33), `test_04_sit_execution_and_settlement.py` (27), `test_05_incidents_and_disputes.py` (16), `test_06_workflows_and_endpoints.py` (13), `test_07_security_and_rbac.py` (9).

### Stage-2 tag audit result

**PASS** — 126 test functions, each with exactly one `Design:` tag; all 98 tags resolve to real instances (28 Difficulty + 70 Corner non-stub); no untagged, dual-tagged, or dangling tags; all 16 Corner stubs untranslated with valid difficulty-instance pointers.

## Step 6: Generate Implementation — 2026-08-12T21:30:00.000Z

Subagent summary (verbatim):

All test servers are cleaned up (the earlier count of 3 was the grep pipeline itself racing; the final check shows zero). The implementation is complete and verified.

## Summary

**File list** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/workspace/implementation/`):

| File | Lines | Purpose |
|---|---|---|
| `start.sh` | 10 | Launcher: guarded `pip install` (no-op when Flask present), `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 78 | App factory, blueprint registration, ApiError/404/405/500 envelope handlers |
| `db.py` | 23 | In-memory dict store (12 entity tables) + insertion sequence; starts empty |
| `clock.py` | 15 | Logical clock, default `2026-08-01T00:00:00Z`, never wall-clock |
| `errors.py` | 45 | `ApiError` + all 25 error-ID constants |
| `middleware.py` | 89 | `X-User-ID`/`X-User-Role` auth (400), RBAC (403), pagination (limit 10/[1,100], offset 0) |
| `response.py` | 45 | Envelope: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields in `meta` for lists |
| `serializers.py` | 204 | Exact per-entity public field sets; Decimal→number, datetimes→ISO8601 3-fractional-digit `Z` |
| `util.py` | 97 | Monotonic-first-segment UUIDs (so `(created_at, id)` ledger replay order is chronological), Decimal half-up 2dp, `touch()` version/updated_at bumps |
| `routes/clock_routes.py` | 28 | Clock set + expiry cascade |
| `routes/members.py` | 242 | Apply, list/get, accept-liability, submit-references, finalize-vetting, suspend, reinstate, remove |
| `routes/references.py` | 168 | Reference CRUD + accept/reject/withdraw + reciprocal auto-linking |
| `routes/pets.py` | 104 | Pet profiles create/list/get/deactivate |
| `routes/holidays.py` | 93 | Holiday windows create/list/get/disable |
| `routes/requests.py` | 215 | Request posting (offer pricing, credit floor), list/get, cancel with late-sitter penalty |
| `routes/claims.py` | 241 | Claim create/list/get + OCC-guarded accept cascade, reject, withdraw |
| `routes/assignments.py` | 110 | Get, per-request lookup, checkout, settle |
| `routes/handoffs.py` | 186 | Handoff lookup (ciphertext masking), PUT, confirm-handoff/return, report-lost |
| `routes/entries.py` | 121 | Entry-log append (window + handoff gates, CHECK_IN transition) and list |
| `routes/incidents.py` | 174 | File/list/get, begin-review, resolve (AT_FAULT/NO_FAULT), dismiss |
| `routes/disputes.py` | 270 | Open/list/get, assign-mediator, resolve (credit adjustment + auto-settle), escalate |
| `routes/ledger.py` | 27 | Credit-ledger list in `(created_at, id)` replay order |
| `services/calc.py` | 162 | Offer pricing, settlement variants, ledger append, reliability clamp, overlap |
| `services/cascade.py` | 140 | Expiry, suspension/removal cascades, removal eligibility |

**Total: 2,888 lines.**

**Endpoint coverage: 44/44** — every row of the PRD §4 endpoint table is implemented (clock, 10 member ops, 6 reference ops, 4 pet ops, 4 window ops, 4 request ops, 6 claim ops, 4 assignment ops, 5 handoff ops, 2 entry-log ops, 6 incident ops, 6 dispute ops, ledger list).

**State machines:** all 8 implemented with scaffold-exact preconditions and side effects — Member (APPLIED→REFERENCES_PENDING→VETTED↔SUSPENDED, →REMOVED terminal), MemberReference (reciprocal auto-link on accept), SittingRequest (OPEN→ASSIGNED via claim accept, CANCELLED, EXPIRED via clock), SittingClaim, SittingAssignment (CONFIRMED→IN_PROGRESS→COMPLETED_PENDING_REVIEW→SETTLED, DISPUTED round-trip, both cancel paths), AccessHandoff (incl. auto-incident + −10 reliability on LOST), Incident, Dispute (incl. ESCALATED_REMOVAL → −25).

**Calculations:** offer = duration × max intersecting enabled multiplier (no compounding, locked at posting, survives window disable); settlement final variant with >25 % early-departure repricing at 0.5× rate; late-cancel penalty (`<24 h` strictly, 0.25× offer, −8 reliability); incident penalty (0.5× settled, only when SETTLED); event-wise reliability clamped [0,100], floor 30 for claims; ledger-derived balances; 365-day ≥2 at-fault removal eligibility. All money in `Decimal`, round-half-up 2dp.

**Validations:** enforced in §2.7 pipeline order (auth → RBAC → left-to-right path existence → OCC `expected_sitting_request_version` → state → ownership → vetting → reliability → reciprocity → overlap → handoff timing/completion → entry window → credit → pet → self-dealing → field → unresolved-incident → removal), each with the catalog's exact error ID and HTTP status.

**One deliberate judgment call:** the spec's literal "referee must be VETTED at reference accept" combined with the mutual-reference rule is mathematically unbootstrappable (no first member can ever be vetted, which would make every claim/settlement/dispute flow unreachable). Accept therefore rejects only SUSPENDED/REMOVED referees with `ERR_REFEREE_NOT_VETTED`; APPLIED/REFERENCES_PENDING referees may vouch so the mutual-vouching web can form. All other gates (≥2 PENDING/ACCEPTED, reciprocity, liability) are literal.

**Verified:** 4 smoke suites (≈120 behavioral assertions) covering auth, vetting + reciprocity failure, pricing with overlapping windows, OCC 412, overlap/adjacency, handoff timing + ciphertext masking, entry windows, checkout/settle math (full and early-departure), late-cancel penalty and 24 h boundary, incident blocking + at-fault penalties, dispute mediation/credit adjustment/escalation, removal via both eligibility paths, suspend cascade, expiry cascade, filters and pagination.

**start.sh contract:** executable; honors `$PORT` (default 10000); binds `0.0.0.0`; runs in the foreground via `exec`; dependency install guarded by `python3 -c "import flask"`; verified booting cleanly from a fresh process with an empty store and no carry-over across kills. No seeding anywhere (grep-audited).

## Step 7: Run Tests and Iterate — 2026-08-12T21:55:00.000Z

Subagent summary (verbatim):

Summary:

- **Iterations run:** 3 sweeps of 8 parallel rounds (24 full 126-test rounds total). Final sweep: **126/126 passed in all 8 rounds**, zero failures, zero errors.

- **Tests deleted:** none. Every failing test traced to PRD prose; no PRD-silence or unique-derivability deletions were needed.

- **Fixes applied to `test_helpers/`:**
  1. `test_helpers/fixtures.py` — `bootstrap_founders()` called `api_client.finalize_vetting(ids[key])` without the required `headers` argument (§4: finalize-vetting is CoopAdmin-only), causing a `TypeError` that cascaded into 917/920 failures across 115 tests in round 1. Added the missing `ADMIN` argument. (Triage-hint case: one upstream fixture bug masquerading as 115 implementation bugs.)
  2. `test_helpers/api_client.py` — added `Connection: close` as a session default header in `ApiClient.__init__`. Under per-test-server isolation the pooled keep-alive connection outlives the per-test server process; the first request of the next test intermittently hit a half-open socket (`ConnectionResetError`/`RemoteDisconnected` on random tests each round). Forcing a fresh TCP connection per request eliminated the flake class.

- **Fixes applied to `test_suite/`:**
  1. `test_06_workflows_and_endpoints.py` — added missing `resolve_incident_at_fault` to the `test_helpers` import list (used at two call sites; `NameError` in both `TestReliabilityEventwiseClamp` tests).

- **Fixes applied to `implementation/`:**
  1. `workspace/implementation/routes/claims.py` — `create_claim()` rejected non-VETTED claimants with `ERR_MEMBER_NOT_VETTED` at claim-creation time. PRD §3.4 names only `ERR_SELF_REFERENCE` and `ERR_RELIABILITY_TOO_LOW` as claim-time rejections, and explicitly attaches the vetting check to acceptance ("the claimant must currently be `VETTED` (`ERR_MEMBER_NOT_VETTED`)"); since suspension withdraws PENDING claims, a claim-time gate would make the PRD-mandated accept-time check unreachable. Removed the vetting gate at creation (kept the `claimer is None` guard and the accept-time check). This made `TestClaimsAndAcceptance::test_unvetted_claimant_accept_rejected` pass.

- **Note for Step 8 (Finalize PRD):** one ambiguity surfaced — §3.4's opening "A vetted member who wants the sit claims an `OPEN` request…" admits a claim-time vetting-gate reading. The resolved behavior (vetting checked at acceptance only) matches the SCAFFOLD's `applies_to: "claim acceptance, mediator assignment, reference acceptance"`; Step 8 may want to make that explicit in the PRD prose.

## Step 8: Finalize PRD — 2026-08-12T22:05:00.000Z

Subagent summary (verbatim):

Done. PRD_FINALIZED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/workspace/PRD_FINALIZED.md` with exactly one revised line.

**Line counts and delta:** PRD.md 293 lines, PRD_FINALIZED.md 293 lines — 0.0% line-count delta (one in-place sentence revision on line 164).

**Changes (one bullet per change):**
- §3.4 (Claiming and Assignment Formation) — revise — opening sentence changed from "A vetted member who wants the sit claims an `OPEN` request…" to "A member who wants the sit claims an `OPEN` request…; vetting standing is not a gate at claim time — the requirement that the claimant be `VETTED` is enforced at acceptance" — `implementation/routes/claims.py:42-52` (creation-time checks: claimer-record existence, reliability floor, self-dealing; no `vetting_status` check) and `implementation/routes/claims.py:124-127` (sole vetting gate at acceptance).

**Step-7 items that required no PRD edit (pure fixture/test-infra bugs):**
- `test_helpers/fixtures.py` missing `ADMIN` header on `finalize_vetting` — PRD §4 already pins finalize-vetting as CoopAdmin-only (line 210); the bug was in the fixture, not the PRD.
- `test_helpers/api_client.py` `Connection: close` default header — test-harness flake under per-test-server isolation; nothing PRD-relevant.
- `test_suite/test_06_workflows_and_endpoints.py` missing `resolve_incident_at_fault` import — test bug only.

**Per-edit pre-edit search log:**

Edit 1 (§3.4 opening sentence):
- (a) Subject: whether a claimer's `VETTED` standing gates claim *creation*, or only claim *acceptance*.
- (b) Impl paths enumerated and read/grepped:
  - `implementation/routes/claims.py:36-72` `create_claim()` — full check chain read: role → request existence → `OPEN` state → `claimer is None` → reliability ≥ 30 → owner self-dealing → message validation. Confirmed no `vetting_status` comparison.
  - `implementation/routes/claims.py:94-200` `accept_claim()` — lines 124-127: the only `vetting_status != "VETTED"` → `ERR_MEMBER_NOT_VETTED` gate.
  - `implementation/routes/claims.py:203-241` `reject_claim`/`withdraw_claim` — no vetting involvement.
  - `implementation/services/cascade.py:49-77` `suspend_cascade` — withdraws the member's `PENDING` claims; consistent with claims being creatable by non-vetted members.
  - Repo-wide grep for `ERR_MEMBER_NOT_VETTED` / `vetting_status` — only the two claims.py sites plus unrelated reference/mediator/suspend/finalize paths (`routes/references.py:116`, `routes/disputes.py:150`, `routes/members.py`), none of which create claims.
  - PRD-side grep for "vetted" — confirmed line 166 (acceptance paragraph) already pins the accept-time check and §2.7 step 7 stays generic; no other PRD sentence touches claim-time vetting.
- (c) Wording adjustment: the impl does raise `ERR_MEMBER_NOT_VETTED` at creation when the caller's `X-User-ID` matches no member record (claims.py:42-46), so the wording deliberately says "vetting standing is not a gate at claim time" rather than claiming no vetting-related error can occur there — it scopes the statement to `vetting_status` checking only, keeping the nonexistent-member path un-mis-described. Also kept "enforced at acceptance, as described below" to point at the already-correct line 166 rather than restating check details, avoiding any redefinition risk.

## Step 9: Complete PRD — 2026-08-12T22:20:00.000Z

Subagent summary (verbatim):

Step 9 complete. `/home/ubuntu/github/CodingPRD/tasks/task_1302_neighborhood_pet_sitting_cooperative/workspace/PRD_COMPLETED.md` produced as a minimal inline patch over PRD_FINALIZED.md.

**Size**: PRD_FINALIZED.md 293 lines / 40,549 chars → PRD_COMPLETED.md 293 lines / 43,713 chars. Char delta **+3,172**; 22 lines revised in place, 0 lines added or removed (no new sections, no new paragraphs).

**Counts**: 16 ambiguity-pins, 6 mismatch-revisions (22 edited lines total; each line carries one change).

**Changes** (section — insert|revise — ambiguity|mismatch — what — impl source):

- §2.2 — insert — ambiguity — 0-or-1-element array lookups (assignment-for-request, handoff-for-assignment) omit pagination fields from `meta` — response.py:34-36, assignments.py:40-46, handoffs.py:56-64
- §2.3 — insert — ambiguity — list sort ties broken by creation/insertion order; non-integer `limit`/`offset` falls back to default, out-of-range values clamped not rejected — middleware.py:53-78
- §2.3 — insert — ambiguity — boolean filters (`active`, `enabled`) accept `true`/`false` case-insensitively, other values ignored — middleware.py:81-89
- §2.4 — revise — mismatch — removal-zeroing `MEDIATION_ADJUSTMENT` entry has no originating dispute and leaves `dispute_id` null — services/cascade.py:130-137
- §2.6 — revise — ambiguity — clock endpoint *sets* (not only advances) to `to_iso8601`; unparseable value → `ERR_INVALID_REQUEST` — routes/clock_routes.py:15-28
- §2.8 — insert — ambiguity — child id existing under a different parent does not resolve → `ERR_NOT_FOUND` — routes/claims.py:100-105
- §2.9 — revise — ambiguity — `version` starts at 1 (was "starts low") — util.py:83-91
- §2.11 — revise — mismatch — `expected_sitting_request_version` is optional; version check runs only when present — routes/claims.py:108-115
- §3.1 — insert — ambiguity — duplicate email rejected with `ERR_INVALID_REQUEST` (400) — routes/members.py:53-58
- §3.1 — revise — mismatch — reference creation requires referee to be an *existing* member (not "existing vetted"); unknown referee id → `ERR_NOT_FOUND` — routes/references.py:46-50
- §3.1 — revise — mismatch — reference acceptance requires referee to exist and be neither `SUSPENDED` nor `REMOVED` (pipeline applicants may vouch); not a strict VETTED requirement — routes/references.py:111-119 (confirmed by bootstrap_founders mutual-vouch clique in fixtures)
- §3.1 — insert — ambiguity — suspension cascade also cancels the cancelled assignment's non-terminal sitting request with `cancelled_reason` `OWNER_SUSPENDED`/`SITTER_SUSPENDED` — services/cascade.py:64-76
- §3.1 — revise — ambiguity — 365-day removal window measured from each incident's resolution time; "resolved exactly 365 days ago" (was "dated") — services/cascade.py:87-97, incidents.py:135
- §3.1 — revise — ambiguity — removal requires non-empty `removal_reason` (`ERR_INVALID_REQUEST`); requests cancelled by removal carry it as `cancelled_reason` — routes/members.py:228-231, services/cascade.py:113-126
- §3.3 — revise — ambiguity — `demand_multiplier` range is inclusive [1.0, 3.0] — routes/holidays.py:50-53
- §3.3 — revise — mismatch — "Basic validation runs first" contradicted the pipeline; now states field validation runs in §2.7 pipeline order (after credit step 14 and pet-profile step 15), and `start_at` must be *strictly* in the future — routes/requests.py:68-105
- §3.4 — insert — ambiguity — claim creation requires caller's `X-User-ID` to match a persisted member, else `ERR_MEMBER_NOT_VETTED` — routes/claims.py:42-46
- §3.4 — revise — mismatch — OCC sentence now conditional ("when the payload carries `expected_sitting_request_version`…") matching optional-field impl — routes/claims.py:108-115
- §3.4 — insert — ambiguity — auto-rejected sibling claims in the acceptance cascade get `decided_at` stamped — routes/claims.py:158-166
- §3.4 — insert — ambiguity — request cancellation gated to `OPEN`/`CLAIMED`/`ASSIGNED` (`ERR_INVALID_STATE` otherwise) and requires non-empty `cancelled_reason` (`ERR_INVALID_REQUEST`); cancel-path claim rejections stamp `decided_at` — routes/requests.py:149-176
- §3.5 — revise — mismatch — ciphertext visibility: owner/admin always; sitter from `scheduled_start_at` − 2h onward (no CONFIRMED-state condition, no upper window bound); null otherwise — routes/handoffs.py:45-53
- §3.5 — insert — ambiguity — confirm-return also requires the handoff itself be `HANDED_OFF` (`ERR_INVALID_STATE`) — routes/handoffs.py:127-130

Key findings: the six true mismatches were the optional-vs-required OCC version field, the referee-acceptance gate (impl accepts references from APPLIED/REFERENCES_PENDING referees, rejecting only SUSPENDED/REMOVED — load-bearing for the mutual-vouch bootstrap), the §3.3 "basic validation runs first" ordering claim (impl runs credit then pet-profile checks before field validation per §2.7), the handoff ciphertext reveal rule (time-only gate, owner/admin always see it), the `dispute_id`-always-set claim for `MEDIATION_ADJUSTMENT` entries (removal-zeroing entry leaves it null), and reference creation accepting any existing referee. Everything else in the PRD — state machines, pricing/settlement formulas, penalty fractions, reliability deltas, thresholds and boundary inclusiveness, error catalogue, RBAC table, envelope shapes — already matched the implementation uniquely.
