# Worklog — task_1766_bulky_item_special_curbside_collection

## Step 1: Create Task Directory — 2026-08-14T14:38:00.000Z

Task directory `tasks/task_1766_bulky_item_special_curbside_collection/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher (Step 1 treated as DONE per instructions; no index scan performed, no other task directory touched).

## Step 2: Generate Scaffold — 2026-08-14T15:16:00.000Z

Done. All three scaffold artifacts are written and verified.

**Task**: `task_1766_bulky_item_special_curbside_collection` — municipal bulky-item curbside collection (quota/allocation archetype blended with pricing engine; flat topology, cyclic state machines, segregation-of-duties role model).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1766_bulky_item_special_curbside_collection/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Counts**:
- Entities: **9** (Household, HouseholdAllowance, AmnestyWindow, RouteDay, PickupRequest, PickupItem, FeeAssessment, DumpingReport, Notification)
- Endpoints: **42** (incl. `/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- State machines: **6** (20 transitions) — cyclic PickupRequest (SCHEDULED→REFUSED→SCHEDULED loop with allowance-idempotent re-schedule), cyclic Household (ACTIVE↔SUSPENDED gated on fine settlement), gated RouteDay (OPEN→DISPATCHED→CLOSED with bubble-up close gate), plus AmnestyWindow/DumpingReport/FeeAssessment
- Calculations: **7** — incl. per-item fee chain with pinned per-line-then-sum rounding (8.5% surcharge produces a real 1-cent divergence: 13238 vs 13237), provisional-vs-final invoice (contamination penalty delta), projected-vs-committed route fullness, calendar-year allowance ledger with idempotent re-consume, exponential illegal-dumping fine escalation
- Validations: **14** (priority-ordered; two deliberate cross-category priority conflicts)
- Error catalog: **18** codes, all referenced
- Roles: **4** (Resident entity-backed to Household; Driver/Inspector/Dispatcher opaque; fine determination vs waiver vs reinstatement split across Inspector/Dispatcher for segregation of duties)
- Concurrency: **2** OCC rules (stale RouteDay version on schedule → 412; stale PickupRequest version on cancel → 412)
- §1.8 instances: **18** (2 per rule × 9 rules, all differentiation clauses honored — e.g., dual-variant on two entity domains, combinatorial modes (a) and (b), overlap rules with half-open vs point-equality vs aggregate-capacity semantics, invariants over two different conserved quantities)
- §1.9 instances: **35** across all nine claim-extraction sections

**Verification**: `scaffold_lint.py` verdict is clean (479 calls scanned), and I additionally replayed all 53 test recipes against a from-scratch Python simulation of the scaffold's own state machines, validations, fee math, and OCC rules — every setup chain reaches its target state, every negative trigger produces exactly its pinned error, and all numeric asserts were machine-computed (e.g., 6510 clean vs 9510 contaminated invoice; 25000→50000 fine escalation; cancel cutoff at exactly midnight of pickup day).

**Notable design decisions**: refusal consumes allowance but releases route capacity while miss releases both (the two compensating invariants are deliberately independent); amnesty waives the over-allowance fee but never the refrigerant recovery surcharge, and `amnesty_applied` freezes at scheduling so cancelling a window never reprices; zero-amount assessments stay PENDING (no special-casing); `REMINDER` was dropped from the notification enum to keep enum closure tight.

## Step 3: Copy Shared Files — 2026-08-14T15:17:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1766_bulky_item_special_curbside_collection/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:22:00.000Z

All audits pass. The PRD is complete.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1766_bulky_item_special_curbside_collection/workspace/PRD.md` — 264 lines.

**Section list**:
1. Introduction (3 paragraphs: operational context → role constituencies & segregation of duties → the three engines underneath)
2. Global Specifications & System-Wide Principles
   - 2.1 User and Role-Based Access Control (with per-role `identity:` translation)
   - 2.2 API Response Structure (verbatim fixed block, byte-identical confirmed)
   - 2.3 Pagination
   - 2.4 The Logical Clock (startup default `2026-08-01T00:00:00Z`)
   - 2.5 Common Resource Properties (including the Notification `common_fields: false` exception)
   - 2.6 Money, Units, and Rounding (integer cents; pinned per-item-then-sum half-up order)
   - 2.7 Optimistic Concurrency Control (both OCC rules with exact error IDs)
   - 2.8 Nested and Reverse-Reachable Retrieval (left-to-right validation + reverse graph reads)
   - 2.9 Validation Ordering (all 14 priorities in fixed prose order)
3. Business Logic & Workflows — 7 subsections organized by service lifecycle: 3.1 Household Accounts/Allowances/Standing, 3.2 Building a Request (items, preparation, provisional pricing), 3.3 Route Days/Scheduling/Allowance Ledger, 3.4 Day of Service (dispatch/complete/refuse/miss), 3.5 Fees/Settlement/Disposal Routing, 3.6 Amnesty Weeks and Illegal-Dumping Enforcement, 3.7 Projected vs. Committed Fullness
4. Endpoint Definitions (42 rows, 4 columns, roles verified against scaffold)
5. Error Code Catalogue (18 errors, 2 columns)

**Zero-Silence Rule audit — all PASS**:
- Field coverage: 56 required identifiers (entity fields + endpoint inputs/query params + `to_iso8601`/`current_utc` + common fields), 0 missing.
- Rule coverage: all 14 validation rules with priority ordering expressed in §2.9 and inline near their workflows; both OCC rules fully expressed (write endpoint + `expected_*_version` field + exact error ID + 412 status, no race-framing); all 6 state machines' transitions (from/to/preconditions/side effects) covered, including the REFUSED→SCHEDULED idempotent re-consume rule, the EXCEEDS_DECLARED_ITEMS special case, and the DETERMINED_ILLEGAL transitive cascade (fine creation → household suspension → notification); all 7 calculations reconstructed in prose with constants (2500/4500/1500/1200/3000/25000 cents, 8.5% surcharge, load units 2/3/4/5/2/1 with oversize doubling, 1.5 m / 32 kg oversize threshold, escalation cap 3 with 25000→50000→100000→200000 progression) and pinned boundary semantics (capacity equality allowed; allowance free while remaining ≥ 1; half-open amnesty interval on the scheduled date's midnight instant; ±1-day authorized set-out window; ties broken by `created_at` ascending).
- Path purity: 330 backtick tokens scanned in §3, 0 path/method violations — endpoints referenced by state-pair framing (e.g., `SCHEDULED → COMPLETED`), role+verb, or capability description.
- Every error ID, state value, and enum value present; endpoint table roles match scaffold exactly; no fuzzy words detected.

**Deliberate information-scattering choices**:
- The item-fee quote is told twice from two angles: the provisional variant in §3.2 (submission narrative) and the scheduled variant in §3.3 (scheduling narrative), with the amnesty waiver rule split between §3.3 (mechanics) and §3.6 (policy context).
- The allowance ledger's release rule appears in §3.3 (cancel), §3.4 (miss), and §3.1 (counter semantics), forcing cross-section reconstruction.
- The cancellation cutoff, OCC guard fields, and capacity boundary live in §2.7/§3.3 separately from the endpoint rows in §4.
- Refrigerant's "never waived, even by amnesty" rule is stated in §3.2 and echoed in §3.6 where amnesty is defined.
- The logical clock's reach is stated globally in §2.4 but each temporal rule (day-of dispatch, off-date driver actions, cancel cutoff) is re-anchored in its own §3.3/§3.4 workflow paragraph.
- `setout_classification` and the fine-escalation tie-break are embedded in the §3.6 enforcement narrative rather than any field list.

## Step 5: Generate Unit Tests — 2026-08-14T15:45:00.000Z

(Note: the Step 5 subagent's first turn ended after adjudication analysis without writing files; it was resumed via SendMessage and completed the full generation on the second turn.)

All checks pass. Final summary:

**Task**: task_1766_bulky_item_special_curbside_collection — full test infrastructure generated and collecting cleanly (69 tests, 0 collection errors, 0 skip/xfail markers).

### Tests emitted per queue
- **Queue A (Difficulty)**: 36 tests — all 18 instances covered with exactly ≥2 tests each (verified programmatically against `SCAFFOLD_DIFFICULTY_DESIGN.yaml`).
- **Queue B (Corner)**: 23 tests — 21 of 25 non-stub instances covered (two instances got 2 tests each where the recipe split naturally into success/failure sides of one boundary).

### Skip list (4 instances, all queue B)
| Instance | Reason (PRD-first two-condition failure) |
|---|---|
| `Corner/entities/pickup_item_invalid_category_rejected` | Not uniquely derivable: PRD §3.2 ties unknown-category rejection to **submission** ("submission is rejected with ERR_INVALID_REQUEST when … any item fails schema rules (unknown category…)"); an implementer could accept the item at add-time and reject at submit. The instance asserts rejection at add time. |
| `Corner/entities/pickup_item_duplicate_sequence_no_rejected` | Same ambiguity — §3.2 names duplicated sequence_no as a *submission* rejection; add-time rejection is one of two PRD-consistent variants. |
| `Corner/entities/pickup_request_computed_fields_rejected_as_input` | PRD never states a strict-payload policy; silently ignoring unknown fields is PRD-consistent (fails two-reader test). |
| `Corner/state_machines/dispatch_empty_route_rejected` | PRD §3.4 says an empty route "is not dispatched" but names no error_id for it (ERR_INVALID_STATE vs other is not uniquely derivable; §2.9 does not pin it either). |

### test_helpers file list
`test_helpers/`: `__init__.py` (barrel), `types.py` (9 entities + 12 enums; Notification correctly omits `updated_at`/`version`), `api_client.py` (31 endpoint methods), `api_errors.py` (18 error ids + framework registration), `assertions.py` (per-entity + invariant checkers), `factories.py`, `constants.py` (fee/load/fine constants), `test_users.py` (`make_resident_headers` mandatory builder for the entity-backed Resident role), `fixtures.py` (tiers 1–5: atomic steps, `setup_submitted_request`, `setup_scheduled_request`, `setup_completed_request`, `setup_refused_request`, `consume_allowance` threshold targeting, `suspend_household_via_illegal_dumping`).

### test_suite file list (9 files, reading order simple→complex)
`conftest.py`, `test_01_households_requests_and_items.py`, `test_02_submission_gates.py`, `test_03_fee_calculations.py`, `test_04_amnesty_and_route_fullness.py`, `test_05_scheduling_gates.py`, `test_06_cancel_refuse_miss_cycles.py`, `test_07_day_of_service.py`, `test_08_dumping_enforcement.py`, `test_09_rbac_pagination_and_notifications.py`.

### test_recipe adjustments needed to compile
1. **OCC version threading**: several recipes capture `expected_route_day_version` from route creation but schedule a *second* request afterward; the helper `schedule_request()` does a fresh GET of the route version before scheduling (used only for must-succeed setups); asserted-stale tests pass the stale version explicitly per recipe.
2. **`as: __NO_ROLE__`** (unauthenticated_request_rejected): translated to `api.list_route_days(headers={})` since the framework has no no-role constant.
3. **JSONPath captures like `$.data.0.id`**: translated to Python list indexing on the `data` array (`find_assessment(...)` helper for kind-filtered lookups).
4. **Unused leading setup calls dropped** where a recipe's early steps built a household that the asserted request never used (e.g., per_item_fee_multi_branch's initial clock/household scaffold was kept, but a redundant second household creation was removed); all asserted entity state matches the recipe's pinned values verbatim (6510/9510, 4015/9223/13238, 4883, 2713, 1302, 25000/50000).
5. **`settle_by_non_owner_resident_forbidden`**: asserted `ERR_FORBIDDEN` (not ERR_ASSESSMENT_NOT_SETTLABLE) because PRD §2.1 names FORBIDDEN for ownership mismatch and §2.9 priority (2) authorization precedes (13) settlability — the only uniquely-derivable outcome.

### Verification performed
- `pytest --collect-only`: 69 tests, 0 errors (orchestrator re-verified: 69 collected, 0 errors).
- Tag audit script: every test has exactly one `Design:` tag at docstring end, resolving verbatim to a real instance; all 18 difficulty instances ≥2 tests; all covered corner instances ≥1.
- Citation audit script: all 69 docstring PRD quotes contain an ≥8-word substring surviving literal match against PRD.md (markdown-stripped, whitespace-normalized).

## Step 6: Generate Implementation — 2026-08-14T15:56:00.000Z

Implementation complete and verified. Summary:

## Files delivered

All under `/home/ubuntu/github/CodingPRD/tasks/task_1766_bulky_item_special_curbside_collection/workspace/implementation/`:

- `start.sh` — executable launcher; guards `pip install` behind a `python3 -c "import flask"` check (no-op on per-test reboots), then `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app, blueprint registration, envelope-wrapped 404/405/400/500 handlers, global RLock serializing all requests (safe in-memory mutation under threaded server), `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory dict stores (empty at boot, zero seeding), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, monotonic wall-clock timestamps, formatters
- `errors.py` — `ApiError` + all 18 error-ID constants
- `response.py` — envelope helpers (`meta`/`response_type`/`data`, pagination fields `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401/403), Resident ownership, body/enum/datetime parsing
- `serializers.py` — per-entity wire format (Notifications have no `updated_at`/`version` per PRD 2.5)
- `routes/` — `clock.py`, `households.py`, `amnesty.py`, `route_days.py`, `pickup_requests.py`, `fee_assessments.py`, `dumping_reports.py`
- `services/calc.py` — all calculation rules

## Endpoint count

**42 endpoints** implemented — the full Table 5 list including the clock endpoint, all CRUD, all action endpoints (submit/schedule/cancel/complete/refuse/miss/dispatch/close/window-cancel/reinstate/settle/waive/determine), and all reverse-reachability list endpoints.

## State machines

Six: PickupRequest (DRAFT→SUBMITTED→SCHEDULED→{COMPLETED, REFUSED, MISSED}→CANCELLED incl. REFUSED→SCHEDULED cyclic re-booking), RouteDay (OPEN→DISPATCHED→CLOSED), AmnestyWindow (ACTIVE→CANCELLED), DumpingReport (OPEN→DETERMINED_AUTHORIZED/DETERMINED_ILLEGAL/DISMISSED), Household (ACTIVE↔SUSPENDED via cascade + Inspector reinstate), FeeAssessment (PENDING→SETTLED/WAIVED incl. system-cascade waivers).

## Calculations

All 7: `item_fee_quote` (both provisional worst-case and scheduled variants, Decimal per-item half-up surcharge rounding before summing), `final_invoice` (flat 3000c contamination penalty per distinct flagged item), `allowance_ledger` (lazy per-year rows, strict `remaining > 0` boundary, idempotent re-consume, release on cancel/miss), `request_load_units` (category loads ×2 oversize), `route_fullness` (projected SCHEDULED-only vs committed SCHEDULED+COMPLETED, half-up pct), `disposition_routing`, `illegal_dumping_fine` (25000 × 2^min(priors,3) with reported_at/created_at tie-break).

## PRD ambiguities resolved

1. **REFUSED→SCHEDULED ledger idempotency** — the scaffold formula literally re-processes over-allowance items (double-counting `over_allowance_items`); the PRD calls the ledger "idempotent across this recovery loop." I added an internal `_ledger_counted` marker per item so re-scheduling skips items already counted in *either* counter; release resets it.
2. **Settle ownership failure** — priority-2 rule suggests 403, but PRD §3.5 + validation priority 13 explicitly say a non-owning Resident settling gets `ERR_ASSESSMENT_NOT_SETTLABLE` (409). Chose 409 (PRD wins); 403 still used on reads. [NOTE: Step 5's test asserts ERR_FORBIDDEN under §2.9 priority-2-beats-13 reasoning — a deliberate test/impl divergence for Step 7 to adjudicate.]
3. **Dispatching an empty route** — no error ID specified; chose `ERR_INVALID_STATE` (409) as a state-machine precondition failure.
4. **Complete on a non-DISPATCHED route** — `ERR_ROUTE_LOCKED` is documented as schedule/cancel-only, so used `ERR_INVALID_STATE` (409).
5. **Missing OCC fields / reason codes / FK fields** — treated as schema failures → `ERR_INVALID_REQUEST` (400); version fields when present but mismatched → 412 as specified.
6. **Cancel from REFUSED/MISSED on a locked (dispatched) route** — allowed; the route lock only blocks cancels that would mutate route capacity (i.e., from SCHEDULED), otherwise PRD's "cancel available from SUBMITTED, SCHEDULED, MISSED, REFUSED" would be unsatisfiable.
7. **`created_at`/`updated_at` use monotonic wall clock** (3-fractional-digit ISO), while `reported_at`/`settled_at`/temporal rules read the logical clock — PRD §2.4's "never wall-clock" applies to the enumerated temporal rules; §3.5/3.6 explicitly assign logical clock to reported_at/settled_at only.
8. **PROHIBITED item load** — not in the load map; assigned 0 (such items can only exist in DRAFT since submit rejects them).
9. **Pagination out-of-range values** — clamped (`limit` to [1,100], `offset` to ≥0); non-integer values → 400.

Verified via a 100+-assertion smoke suite (all pass) covering pricing math by hand (2713/4015/7595/4340-cent cases, amnesty keeping refrigerant/oversize/mattress fees), OCC 412s, priority ordering (403-before-404 on household paths, duplicate-date before capacity, prohibited-scan before prep-scan), ledger idempotency, route lock, midnight cancel cutoff, day-of dispatch/driver gates, fine escalation (25000→50000), suspension/reinstate gating, and fresh-boot emptiness with the default clock.

## Step 7: Run Tests and Iterate — 2026-08-14T16:05:00.000Z

Clean 8-round sweep achieved: all 8 rounds at 69/69 passed, 0 failed, 0 errors.

- **Iterations run:** 2 sweeps (16 total rounds). First sweep: 68/69 in every round (one deterministic failure). Second sweep after fix: 69/69 in all 8 rounds.

- **Tests deleted:** None.

- **Fixes applied to `test_helpers/`:** None. (`validate_error_is_one_of` was already exported by `test_helpers/__init__.py`; both `ApiErrorId.ERR_FORBIDDEN` and `ApiErrorId.ERR_ASSESSMENT_NOT_SETTLABLE` already existed in `test_helpers/api_errors.py`.)

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_09_rbac_pagination_and_notifications.py` — `TestSettlementOwnership::test_settle_by_non_owner_resident_forbidden`. STEP 1 adjudication of the known divergence: PRD verbatim-covers the scenario with **two conflicting outcomes** — §2.1 + §2.9 priority (2) ("for `Resident` calls on household-scoped resources, `X-User-ID` equals the owning household's id, else `ERR_FORBIDDEN`") versus §3.5's scenario-specific sentence ("settling a non-pending assessment or one belonging to another household fails with `ERR_ASSESSMENT_NOT_SETTLABLE`"). Two faithful PRD-only readers diverge, so unique derivability fails; per the protocol's permitted coverage correction, relaxed the exact `validate_error(ERR_FORBIDDEN)` + `status == 403` assertion to `validate_error_is_one_of([ERR_FORBIDDEN, ERR_ASSESSMENT_NOT_SETTLABLE])` + `status_code in (403, 409)`, keeping the state assertion both readings agree on (assessment stays `PENDING`). Docstring updated to quote all three PRD sentences and record the ambiguity. No assertion was weakened below what PRD uniquely determines.

- **Fixes applied to `implementation/`:** None. The implementation's choice (409 `ERR_ASSESSMENT_NOT_SETTLABLE` per PRD §3.5) is one of the two PRD-faithful readings and was left intact.

## Step 8: Finalize PRD — 2026-08-14T16:09:00.000Z

The patch is complete and verified. Final state: 264 lines → 264 lines, three surgical revisions, nothing else touched.

**Line counts / delta:** PRD.md 264 lines, PRD_FINALIZED.md 264 lines — 0 lines added/removed (0% delta); 3 lines revised inline.

**Changes (one bullet each):**
- §2.1 (Resident bullet) — revise — appended a carve-out sentence: the assessment-settlement action is the single exception to "ownership mismatch → ERR_FORBIDDEN"; there the mismatch is reported as ERR_ASSESSMENT_NOT_SETTLABLE — `implementation/routes/fee_assessments.py:52-54` (settle folds non-owning Resident into the 409 settlability error).
- §2.9 (validation-ordering priority (2)) — revise — added parenthetical that on the assessment-settlement endpoint the household-ownership mismatch is reported by the priority-(13) settlability rule per §3.5, not as priority-(2) ERR_FORBIDDEN — `implementation/routes/fee_assessments.py:52`.
- §3.5 (settlement paragraph) — revise — appended explicit priority claim: for the settle action the settlability rule supersedes the generic §2.1 ownership rejection; a non-owning Resident receives ERR_ASSESSMENT_NOT_SETTLABLE (409) — `implementation/routes/fee_assessments.py:46-58` (endpoint comment at :50-51 documents exactly this choice).

**Per-edit pre-edit search log (all three edits share one subject domain, searched once and re-confirmed per edit):**

(a) Subject identified: Resident household-ownership mismatch handling — which error code surfaces it, on every endpoint that performs it.

(b) Impl paths enumerated and read/grepped: `middleware.py:32-36` (`require_own_household` → 403 ERR_FORBIDDEN) and every call site — `routes/households.py:56` (GET household), `routes/households.py:96` (`_sublist`: allowances/pickup-requests/fee-assessments sublists), `routes/fee_assessments.py:27` (GET one assessment — a read, still 403), `routes/pickup_requests.py:46` (create), `routes/pickup_requests.py:29-31` (`_own` helper) with call sites at lines 78, 109, 154, 170, 182, 213, 277, 424, 435 (get/add-item/delete-item/list-items/submit/schedule/cancel/request-assessments/request-notifications); plus the sole deviant path `routes/fee_assessments.py:46-58` (settle: role gate 403 for non-Resident at :48, 404 at :49, then 409 ERR_ASSESSMENT_NOT_SETTLABLE for non-PENDING **or** non-owning Resident at :52). Also read `test_suite/test_09_rbac_pagination_and_notifications.py:75-120` (the relaxed test) and the full PRD for any other ownership/ERR_FORBIDDEN claims (§2.1 line 24's "only a Resident may settle" names no error code; §4 table row for settle names no error code — both conflict-free).

(c) Wording adjustments made to keep all enumerated paths consistent: (i) in §2.1 used "The single exception is the assessment-settlement action" — verified against the full enumeration that settle is indeed the only non-403 ownership path; (ii) scoped every carve-out to "a Resident whose X-User-ID does not match" so the role-gate 403 (non-Resident callers of settle, `fee_assessments.py:48`) remains correctly described by the untouched role-permission sentences; (iii) in §2.9 phrased the parenthetical as "reported by the settlability rule of priority (13), per §3.5" rather than asserting a new global ordering, avoiding any claim about existence-vs-ownership check order that the impl does not exhibit; (iv) in §3.5 kept the clause attached to the existing "non-pending … or one belonging to another household" sentence so no non-Resident or non-existent-assessment scenario is mis-described. No wording needed widening beyond these scopings.

## Step 9: Complete PRD — 2026-08-14T16:25:00.000Z

Done. `PRD_COMPLETED.md` produced at `workspace/PRD_COMPLETED.md` — a minimal inline patch over `PRD_FINALIZED.md`, headings/sections unchanged, no behavior invented beyond what `implementation/` exhibits.

**Source vs output:** `PRD_FINALIZED.md` 264 lines / 44,406 chars → `PRD_COMPLETED.md` 270 lines / 50,250 chars (+6 lines, +5,844 chars).

**Counts:** 12 ambiguity-pins, 5 mismatch-revisions (17 edited passages total; several pins bundle multiple impl facts into one inline insert).

**Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref):**

- §2.3 — insert — ambiguity — limit clamped to [1,100], offset clamped ≥0, non-integer limit/offset → 400 ERR_INVALID_REQUEST; `has_more` defined as `offset + returned < total_count` — implementation/response.py:42-56, 23-30
- §2.4 — insert — ambiguity — two timestamp families: `reported_at`/`settled_at`/`current_utc` read the logical clock and serialize as its exact instant; `created_at`/`updated_at` stamp from a monotonic never-repeating wall clock — implementation/db.py:22-52, services/calc.py:266, routes/dumping_reports.py:42
- §2.7 — insert — ambiguity — missing/non-integer OCC guard field → 400 ERR_INVALID_REQUEST at the OCC step (only an integer mismatch yields 412) — implementation/routes/pickup_requests.py:229-234, 286-291
- §2.7 — insert — ambiguity — server fully serializes request handling (global lock; no interleaved half-applied state) — implementation/app.py:16-28
- §2.9 — revise — mismatch — scoped ordering refinements: schedule evaluates the request's own state gate (incl. EXCEEDS_DECLARED_ITEMS bar) before body-FK lookup and route-OPEN gate before OCC; cancel's route-lock gate precedes the version check; complete's item-id existence check precedes the state gate; ownership-on-read resolves the resource first (404 before 403) — implementation/routes/pickup_requests.py:212-234, 278-291, 350-362, 74-79
- §3.1 — insert — ambiguity — `street_address` validated only as a non-blank string; invalid zone/negative-or-non-integer allowance → 400 — implementation/routes/households.py:29-34
- §3.2 — insert — ambiguity — item-add validates per field at creation: sequence_no int ≥1 unique, category enum, is_oversize boolean when present, `preparation_ack` required boolean; add/remove outside DRAFT → ERR_INVALID_STATE — implementation/routes/pickup_requests.py:105-163
- §3.2 — insert — ambiguity — PROHIBITED items contribute 0 load units — implementation/services/calc.py:36
- §3.2 — revise — mismatch — submit ordering: per §2.9 the empty-list/schema check runs last, after prohibition scan, preparation scan, and the ACTIVE-standing check (was prose implying schema-first) — implementation/routes/pickup_requests.py:183-198
- §3.3 — insert — ambiguity — RouteDay creation requires integer capacities with no positivity constraint; strict yyyy-mm-dd route_date; violations → 400 — implementation/routes/route_days.py:30-37
- §3.3 — revise — mismatch — rebooking after an EXCEEDS_DECLARED_ITEMS refusal fails with ERR_INVALID_STATE (previously unnamed error) — implementation/routes/pickup_requests.py:217-219
- §3.3 — revise — mismatch — cancel-from-SCHEDULED on a non-OPEN route fails with ERR_ROUTE_LOCKED; cancel-from-REFUSED also waives any pending quote and emits CANCELLATION_NOTICE, and is permitted on dispatched/closed routes — implementation/routes/pickup_requests.py:282-284, 310-315
- §3.4 — revise — mismatch — dispatch requires OPEN (else ERR_INVALID_STATE) and ≥1 committed stop (empty → ERR_INVALID_STATE); the dispatch lock covers only capacity-mutating transitions (schedule, cancel-from-SCHEDULED) — REFUSED/MISSED cancels stay allowed — implementation/routes/route_days.py:84-91, routes/pickup_requests.py:282-284
- §3.4 — revise — mismatch — all three driver actions additionally require the route DISPATCHED else ERR_INVALID_STATE; close from non-DISPATCHED → ERR_INVALID_STATE — implementation/routes/pickup_requests.py:327-331, 361-365, routes/route_days.py:99-100
- §3.4 — insert — ambiguity — `improper_preparation_item_ids` optional (default []), non-list → 400, unknown/foreign ids → 404 before the state gate, duplicate ids counted once; penalty folds into FINAL_INVOICE with no separate CONTAMINATION_PENALTY assessment — implementation/routes/pickup_requests.py:350-360, 371-373
- §3.4 — insert — ambiguity — REFUSAL_NOTICE message carries the reason code plus per-category preparation instructions for every item on the request; missing/unknown reason codes on refuse/miss → 400 after the state/route/date gates — implementation/services/calc.py:283-287, routes/pickup_requests.py:386-388, 403-405
- §3.5 — insert — ambiguity — waive on a non-PENDING assessment → ERR_INVALID_STATE (409); CONTAMINATION_PENALTY noted as an enum member that is never emitted — implementation/routes/fee_assessments.py:65-66, services/calc.py:242-257
- §3.6 — revise — mismatch — the determination is recorded as the report's terminal `status`; no separate `determination` field exists on the wire — implementation/routes/dumping_reports.py:95-119, serializers.py:118-129
- §3.7 — insert — ambiguity — `projected_fullness_pct` defined as 0 when `max_load_units` is 0 — implementation/services/calc.py:213-216

**Already-pinned behaviors verified against impl with no change needed:** per-item-then-sum Decimal half-up surcharge rounding (calc.py:92-119), `_ledger_counted` idempotent re-consume on REFUSED→SCHEDULED (calc.py:144-165), settle-by-non-owner → 409 ERR_ASSESSMENT_NOT_SETTLABLE (fee_assessments.py:46-58), Notification resources omitting `updated_at`/`version` (serializers.py:132-141), logical clock default 2026-08-01T00:00:00Z (db.py:6), refusal keeping allowance / miss releasing it, completion keeping committed counters, fine escalation 25000·2^min(priors,3), half-open non-intersecting amnesty windows, and the full RBAC/error-catalog tables.

**Pipeline complete.** Final tree: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 9 test files, 69 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ with start.sh + 8 passing results.{1..8}.json}. Test status: 69/69 passed in all 8 rounds of the final stability sweep.
