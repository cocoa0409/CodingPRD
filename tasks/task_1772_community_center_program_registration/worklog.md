# Worklog — task_1772_community_center_program_registration

## Step 1: Create Task Directory — 2026-08-14T15:01:37.821Z

Task directory `tasks/task_1772_community_center_program_registration/` with `workspace/` subdirectory was pre-created and pre-assigned by the pipeline dispatcher; Step 1 treated as DONE per instructions (no index scan, no writes outside this directory).

## Step 2: Generate Scaffold — 2026-08-14T15:44:55.714Z

## Scaffold generated: task_1772_community_center_program_registration

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — `scaffold_difficulty_design:` only
- `SCAFFOLD_CORNER_DESIGN.yaml` — `scaffold_corner_design:` only

**Counts**
- Entities: **14** (Season, Program, Room, Instructor, ClassSession, ClassMeeting, InstructorContract, Household, Participant, SafetyForm, ScholarshipApplication, Registration, PaymentTransaction, AttendanceRecord)
- State machines: **11** (incl. Registration's two parallel axes — enrollment × payment — modeled as separate machines, plus a cyclic scholarship review loop and branching ClassSession lifecycle)
- Calculations: **10** (fee engine, family-discount threshold, age eligibility, waitlist selector, tiered refund w/ 3 variants, instructor settlement w/ 2 basis variants, scholarship budget, absence replay, room overlap w/ buffer, instructor overlap w/o buffer)
- Validations: **38** (strictly ordered across 8 categories)
- Endpoints: **63** (incl. `POST /seasons/{id}/sweeps` ops checkpoint and `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Error codes: **38**
- Roles: **6** (HouseholdManager/Instructor entity-backed; ProgramCoordinator, FrontDeskStaff, ScholarshipReviewer, FinanceOfficer opaque; segregation-of-duties on scholarship approve)
- Concurrency rules: **2** (OCC on ClassSession.version for `POST /registrations` and `PATCH /class-sessions/{id}`)
- §1.8 difficulty instances: **22** (every rule ≥2; combinatorial_formula has 3 covering modes a/b/c; boundary and cross-entity have 3 each)
- §1.9 corner instances: **37** total (33 active + 4 `excluded_because` stubs citing §1.8 instances)

**Verification**: `scaffold_lint.py` → `VERDICT: clean lint` (993 calls scanned, 0 violations). Additional scripted audit: all `grounds` resolve into §1.1–§1.7, all 59 instance names unique across both design files, zero unbound `${var}` placeholders, forbidden race vocabulary absent. All formula-derived asserts were pre-computed as literals in Python (e.g., fee 15001 → scholarship 25% → 11251 → family 10% → **10126**; instructor per-line rounding **834** vs sum-then-round 833; ATTENDANCE_BASIS divergence **10000 vs 5000**).

**Notable design decisions (max-difficulty levers)**
- **Pinned-at-creation fee semantics**: `fee_charged_cents` computed once — later residency flips, scholarship approval/revoke, or sibling drops never recompute it (revocation only releases the budget commitment).
- **Priority chains**: resident-only window gates nonresidents before duplicate checks; state errors beat temporal errors; safety-signature errors beat duplicate-form constraints — each exercised by a dual-failure instance.
- **Cascade web**: sweep min-enrollment cancellation runs a 4-hop chain (session → registration → refund payment → household credit) with a parallel contract-termination branch; voluntary drop and no-show auto-drop (3-consecutive-absence replay where EXCUSED neither increments nor resets) each re-trigger waitlist promotion with a fresh 48h payment deadline enforced by the next sweep.
- **Compensating invariants**: seat conservation across drop+promotion (`enrolled_count` unchanged) and money conservation on cancellation (per-registration `refund_total == net_paid`, household credit delta equals net_paid, WAIVED registrations move zero).
- **Interval semantics split**: room occupancy is half-open with a 15-minute turnover buffer (11:14 conflicts, 11:15 free); instructor double-booking is unbuffered half-open (back-to-back allowed, 1-minute overlap rejected).

## Step 3: Copy Shared Files — 2026-08-14T15:45:14.519Z

Copied `./INSTRUCTION.md` → `tasks/task_1772_community_center_program_registration/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T15:58:32.888Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/workspace/PRD.md` — 331 lines. The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

**Section list:**
- §1 Introduction (2 paragraphs — business context + design pillars angle)
- §2 Global Specifications: 2.1 User/RBAC · 2.2 API Response Structure (verbatim block, anchors `req_RANDOMALPHANUM123456` / `2025-05-24T10:30:00.123Z` / `UNIQUE_ERROR_IDENTIFIER_STRING` / `"data": { }` confirmed byte-present) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Monetary Values, Cents, and Rounding · 2.7 Optimistic Concurrency Control · 2.8 Validation Order and Error Precedence · 2.9 Booking Intervals and Conflict Semantics · 2.10 Cascading Consistency and Derived Counters
- §3 Business Logic (9 subsections, organized by lifecycle-timeline): 3.1 Seasonal Catalog · 3.2 Sessions, Meetings, Room Assignment · 3.3 Contracts and Publication · 3.4 Households, Participants, Safety Clearance · 3.5 Scholarship Review Cycle · 3.6 Registration: Windows, Eligibility, Pinned Fee · 3.7 Payment and Credit Ledger · 3.8 Drops, Refunds, Waitlist Promotion · 3.9 Attendance, Completion, Season Sweep
- §4 Endpoint Definitions (63 rows, 4 columns) · §5 Error Code Catalogue (38 rows, 2 columns)

**Zero-Silence / Hard Contract audit results:**

```
Field coverage check (Contract 1):
- entities[].fields: 75 required, 75 present, 0 missing
- endpoints[].request_body/input: 54 required, 54 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
- endpoints[].query_params: 2 required, 2 present, 0 missing
Status: PASS

Rule coverage check (Contract 2):
- validations[] with priority: 38 checked, 38 expressed (global 7-rung ladder in §2.8 plus pinned per-endpoint orderings in §3.2, §3.3, §3.4, §3.5, §3.6, §3.7, §3.9), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_class_session_version + ERR_STALE_VERSION/412 all named, purely stale-version framing), 0 missing
- state_machines[].transitions: 49 checked, 49 fully expressed (attendance's six symmetric PATCH transitions rendered as one equal-density cross-product rule), 0 missing
- calculations[]: 9 checked, 9 fully expressed in precise prose (nested roundings pinned, floor/halfway, per-line-then-sum, boundary pins all reconstructible), 0 missing
- validations[] conditions: 38 checked, 38 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 63 checked, 63 expressed, 0 missing
- entities[].fields[] structured content: 75 checked, 75 reconstructible (defaults, null-until semantics, pinned-at-creation, computed sources), 0 missing
- sibling-branch symmetry: 8 groups checked (refund variants, settlement bases, cascade branches, withdraw from-states, re-verification directions, tender methods, contract terminals, attendance transitions), 8 with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only, Contract 3):
- backtick tokens scanned: 538
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Notable scattering / ambiguity-handling decisions:**
- **Overlap-check semantics split deliberately**: the interval algebra (half-open, 15-minute room buffer vs. zero instructor buffer, adjacency/back-to-back pins, non-terminal-session candidate sets) lives in §2.9 as a cross-cutting contract; §3.2 references it narratively and pins the check ordering (capacity → availability → room conflict → instructor conflict) for both create and re-assignment.
- **Priority ordering rendered twice**: §2.8 gives the global precedence ladder (auth → role → well-formedness → left-to-right existence → state legality → OCC → domain gates); each §3 workflow then pins its local order (e.g., publish reports `ERR_CONTRACT_NOT_ACCEPTED` before `ERR_NO_MEETINGS`; approve runs segregation-of-duties before the budget cap; registration's gauntlet runs OCC → season gates → session-open → three window checks in chronological logic → duplicate → age → household membership).
- **Unit-conversion scattering per the skill's guidance**: the 10000-cent refund review threshold is introduced as "one hundred dollars — 10000 cents" then referenced as "the one-hundred-dollar review threshold"; payment windows appear as "seventy-two hours — three days" and "forty-eight hours — two days".
- **`SEASON_NOT_PUBLISHED` vs. `SEASON_CLOSED` overlap resolved** by assigning each gate a distinct trigger (DRAFT-season attempts vs. CLOSED-season attempts) while preserving the scaffold's priority-7-before-8 evaluation order — consistent with both error descriptions and the close transition's side effect.
- **`refund_total_cents` semantics** pinned to the state-machine side effects (incremented when a REFUND reaches `COMPLETED`, immediately or via Finance approval) rather than the looser field-description wording, avoiding a double-count reading for `PENDING` refunds.
- **Two audit-harness false alarms worth noting**: a naive backtick-pairing scan across the whole file flips parity at §2.2's fenced JSON blocks (fences must be stripped before Contract 1/3 extraction), and the fuzzy-word scan flags "reasoning about" — a verb usage, not numeric approximation; both numeric approximator bans are otherwise clean.

## Step 5: Generate Unit Tests — 2026-08-14T16:31:54.287Z

## Summary

**Test counts**
- Queue A (Difficulty): 22/22 instances covered, exactly 2 tests each → **44 tests**
- Queue B (Corner): 33 non-stub instances → **32 tests emitted, 1 skipped**
- **Total: 76 tests** (collected cleanly by `pytest --collect-only`; all files compile)

**test_helpers/** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/test_helpers/`
`__init__.py` (barrel), `types.py` (14 entity TypedDicts + 15 status/role enums), `api_client.py` (63 endpoint methods), `api_errors.py` (38-error catalog registered with the framework), `assertions.py` (per-entity + `assert_instant_eq`), `factories.py`, `constants.py` (PRD thresholds + shared clock instants), `test_users.py` (opaque role constants + `make_household_manager_headers`/`make_instructor_headers` per-entity builders), `fixtures.py` (composite chains: `setup_published_session`, `setup_multi_session_catalog`, `setup_household_with_participants`, `setup_household_with_scholarship`, `register_participant` with OCC read-then-write, `register_and_pay`, `review_and_approve_application` with distinct reviewers, sweep/attendance/refund helpers).

**test_suite/** (10 files) — `conftest.py` + `test_01_catalog_and_access.py` (10) · `test_02_registration_windows_and_capacity.py` (11) · `test_03_fees_and_scholarships.py` (9) · `test_04_payments_and_refunds.py` (10) · `test_05_waitlist_and_drops.py` (7) · `test_06_session_sweeps_and_cancellation.py` (10) · `test_07_contracts_and_settlement.py` (9) · `test_08_scheduling_conflicts.py` (5) · `test_09_attendance_and_safety.py` (6)

**Skipped instance (gap stays a gap)**
- `Corner/entities/registration_create_rejects_computed_field_input` — asserts a client-supplied `fee_charged_cents` is rejected 400. PRD §2.8 rung 3 covers only missing/mistyped required fields; nothing in PRD.md says unknown payload keys are rejected, so a PRD-only implementer could legitimately ignore the key and return 201. Fails unique derivability; not weakened, not skip-marked — omitted.

**Stubs (4)** — `waitlist_promotion_side_effects`, `minimum_enrollment_cancellation_cascade`, `scholarship_approval_commits_budget`, `voluntary_refund_tier_side_effects`: not translated; all four `difficulty_instance` cross-references resolve to real queue-A instances.

**Coverage audit results** — every test docstring ends with exactly one `Design:` tag resolving to a real instance; all 44 queue-A tags and 32 queue-B tags verified; every PRD citation (≥8-word spans) greps verbatim (whitespace-normalized) in PRD.md after fixing several quotes that had truncated PRD sentences mid-clause.

**Notable adjudications within translated instances**
- `refund_voluntary_vs_admin_cancellation`: did not assert `refund_total_cents == 10000` while `REFUND_PENDING` — PRD §3.7 states the total grows "at the moment that refund completes". Asserted `payment_status == REFUND_PENDING` + zero household credit instead.
- Dropped absolute `version == 1` assertions (PRD never pins the initial version); relative `observed + 1` arithmetic is asserted on the OCC paths.
- `family_discount_threshold_evaluation_order`: the recipe's refund capture (`$.data[0].id`) points at the CHARGE entry; the test selects the ledger entry with `type == REFUND` (PRD §3.7 chronological ordering) before approve-refund.
- Two multi-registration scenarios (branching paths, min-enrollment boundary) pass `family_discount_threshold: 99` so the default threshold-3 discount cannot perturb the pinned fees the instances assert.

## Step 6: Generate Implementation — 2026-08-14T16:31:54.287Z

## Files (in `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (import check), `exec python3 app.py`, binds 0.0.0.0:$PORT |
| `requirements.txt` | 1 | flask>=2.2 |
| `app.py` | 74 | Flask app, blueprint registration, envelope-shaped 404/405/500 handlers |
| `clock.py` | 20 | Logical clock, startup default 2026-08-01T00:00:00Z, never wall-clock |
| `store.py` | 35 | Empty in-memory dicts + UUID/seq minting (no seeding anywhere) |
| `errors.py` | 59 | ApiError + all 38 catalog error IDs with their HTTP statuses |
| `util.py` | 229 | Envelope (`meta`/`response_type`/`data`), pagination (limit/offset/total_count/has_more, default 10, clamp 1–100), 3-fractional-digit timestamps, field validators, `new_record`/`bump` (version starts at 1) |
| `auth.py` | 41 | X-User-ID + X-User-Role validation, six roles, per-endpoint role lists |
| `services.py` | 545 | All calculations and cascades (below) |
| `routes/*.py` | 1,610 | 15 route modules, one per resource group |

Total ~2,650 lines.

## Coverage

- **Endpoints: 63/63** — verified via Flask's URL map (every method+path pair from the PRD §4 table is registered).
- **Error codes: 38/38** — every ID in the §5 catalog is raised with its exact HTTP status; validation precedence follows the §2.8 ladder (auth → role/identity → well-formedness → existence → generic state → OCC → domain gates) plus the per-endpoint pinned orderings (e.g., publish: season → contract → meetings; meetings: capacity → availability → room overlap → instructor overlap; payment: state → membership → amount → credit; scholarship approve: state → segregation → budget; safety forms: signature → duplicate → membership; scholarship create: duplicate → membership; contracts: duplicate → mismatch).
- **Verified by two smoke waves** (126 + 61 assertions, all passing on fresh boots; boot contract and fresh-boot empty-store/default-clock verified separately).

## Tricky-rule implementation notes

- **Pinned fee** (`services.compute_registration_fee`): computed once at creation; scholarship percent first, then family percent, each step `Decimal` round-half-up (`rhu`); `fee_charged_cents`, `residency_at_registration`, `scholarship_pct_applied`, `family_discount_applied` never recomputed (revoke/re-verify/sibling drops don't touch them — verified by test).
- **Tiered refunds** (`voluntary_refund_amount` + `issue_refund`): VOLUNTARY = 100% if 0 meetings held (`starts_at <= now`, equality counts as held), 50% half-up if `1 <= held <= floor(total/2)`, else 0; NO_SHOW always 0; ADMIN_CANCELLATION always 100%. Issuance: ≥10000 cents → PENDING refund + `REFUND_PENDING`; below → COMPLETED + `REFUNDED` + household credit; 0 leaves PAID; unpaid PENDING → VOID; WAIVED untouched.
- **Waitlist promotion** (`promote_waitlist`): runs once per freed seat after drop/no-show/expiry; candidates ranked `waitlisted_at` ASC, `created_at` ASC, never by id; promoted reg gets `promoted_at`, `payment_due_at = now+48h` if fee > 0 (stays PENDING) else WAIVED; session version bumps once for the drop decrement and again for the promotion (PRD's explicit double-bump).
- **Sweep cascade** (`run_sweep`): step 1 expires ENROLLED+PENDING regs with `payment_due_at <= now` in `payment_due_at`/`created_at` order, each immediately triggering promotion (in-sweep promotions get +48h so can't re-expire); step 2 (only while season PUBLISHED) evaluates PUBLISHED sessions with `enrollment_check_at <= now` in `enrollment_check_at`/`created_at` order — activate at `enrolled_count >= min_enrollment` (equality passes) else LOW_ENROLLMENT cancellation with the full cascade (ENROLLED → CANCELLED with 100% refunds, WAITLISTED → CANCELLED/VOID, contract ACCEPTED → TERMINATED with `cancellation_guarantee_cents`, OFFERED → VOID/0). Returns the four summary id lists.
- **OCC**: `expected_class_session_version` required (400 if missing) on POST /registrations and PATCH /class-sessions; mismatch → 412 `ERR_STALE_VERSION` evaluated after existence and (for PATCH) after generic state legality, before all domain gates. Every cascade-touched entity independently bumps `version`/`updated_at`.
- **Interval conflicts**: rooms use half-open `[starts_at, ends_at+15min)` (adjacency at exactly `ends_at+15min` allowed); instructors use unbuffered half-open `[starts_at, ends_at)` (back-to-back allowed); candidates restricted to meetings of DRAFT/PUBLISHED/ACTIVE sessions; PATCH excludes self. Room check runs before instructor check.
- **Other pins**: settlement rounds each per-registration line first, then sums, then applies the guarantee floor; ATTENDANCE_BASIS qualifies at exactly 50% via integer-exact `2*present >= meetings_held`; absence replay walks held meetings in `starts_at`/`created_at` order (PRESENT resets, ABSENT +1, EXCUSED unchanged), fires the NO_SHOW drop at exactly 3 once (corrections never resurrect); the clock endpoint echoes `to_iso8601` verbatim as `current_utc`.

One judgment call worth flagging: PRD §3.1's catalog-creation gate is internally contradictory ("neither DRAFT nor PUBLISHED → ERR_SEASON_NOT_PUBLISHED" vs "CLOSED → ERR_SEASON_CLOSED" for the same state); I implemented CLOSED → `ERR_SEASON_CLOSED` for program/session/meeting creation, matching the explicit sentences and the error-catalog entry.

## Step 7: Run Tests and Iterate — 2026-08-14T16:40:08.435Z

## Summary

**Iterations run:** 2 (initial sweep identified failures; fix applied; confirmation sweep passed 8/8 rounds, 76/76 tests each).

**Tests deleted:** None.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/test_suite/test_06_session_sweeps_and_cancellation.py` — `_sweep_chain_scenario()` (shared setup for `test_sweep_cancellation_chain_registration_hops` and `test_sweep_cancellation_chain_money_and_contract_hops`). The fixture created the session with `capacity=1, min_enrollment=2`, which violates PRD §2.8 rung 3 / §3.2 ("min_enrollment at least one and no greater than capacity"), so the PRD-faithful implementation correctly rejected creation with `ERR_INVALID_REQUEST` at setup. Rebuilt the scenario PRD-legally to reach the identical sweep-time geometry (PUBLISHED session, enrolled_count 1 < min_enrollment 2, one ENROLLED+paid registration, one WAITLISTED unpaid registration): create at capacity 1 / min_enrollment 1, register R1 (fills the seat, paid), waitlist R2, then apply the OCC-guarded PATCH of §3.2 raising capacity and min_enrollment to 2 — the patch's only floor check is `capacity >= enrolled_count` (satisfied: 2 ≥ 1), and PRD §3.8 names no promotion trigger on a capacity increase, so R2 stays WAITLISTED with the seat formally open until the sweep cancels the session `LOW_ENROLLMENT`. All assertions in both tests (verbatim PRD §3.9 cancellation-chain rules) were left untouched.

**Fixes applied to `implementation/`:** None — the implementation was already PRD-faithful; the failure was purely the test fixture issuing a PRD-invalid creation payload.

## Step 8: Finalize PRD — 2026-08-14T16:43:22.489Z

## Summary

**Line counts / delta:** `PRD.md` = 330 lines; `PRD_FINALIZED.md` = 330 lines; **0% delta** — `cmp` verifies the two files are byte-identical.

**Changes:** None. Zero edits were needed.

**Why zero edits:** The only `<step_7_diff>` item is a pure fixture bug. The original `_sweep_chain_scenario()` created a session with `capacity=1, min_enrollment=2` — a payload the PRD already forbids verbatim in two places: §2.8 rung 3 ("`min_enrollment` at least one and no greater than `capacity` … Violations are `ERR_INVALID_REQUEST`", PRD.md line 113) and §3.2 ("a `min_enrollment` (at least one and no greater than `capacity`)", line 141). The implementation enforces exactly this at `implementation/routes/sessions.py:64-67` and correctly rejected the PRD-invalid payload. Step 7 applied no implementation fixes and no test deletions, and the step_7_diff itself classifies the failure as "purely the test fixture issuing a PRD-invalid creation payload."

Everything the rebuilt fixture relies on is likewise already pinned by the PRD, confirmed against the implementation:

- **Create at capacity 1 / min_enrollment 1; R1 ENROLLED+paid, R2 WAITLISTED** — §3.6's seat rule ("If the session's `enrolled_count` has already reached `capacity`, the newcomer is `WAITLISTED` … otherwise it is `ENROLLED`"); impl `services.py:164-176`.
- **OCC-guarded PATCH raising capacity/min_enrollment to 2 with enrolled_count 1** — §2.7 (guard) and §3.2's pinned patch order ("generic state legality comes first, then staleness, then the capacity floor") and floor ("`capacity` may never drop below the session's current `enrolled_count`"); impl `sessions.py:128-143` (floor at line 142: `effective_capacity < enrolled_count` → `ERR_CAPACITY_BELOW_ENROLLED`; 2 ≥ 1 passes).
- **No promotion on capacity increase** — §3.8/§3.9 enumerate all promotion triggers (voluntary ENROLLED drop, no-show drop, sweep step-one expiry); grep of all `promote_waitlist` call sites finds exactly those three (`services.py:287`, `services.py:299`, `services.py:472`) and none in `patch_session`. The fixed test's own docstring derives "R2 stays WAITLISTED" from the PRD ("PRD §3.8 names no promotion trigger on a capacity increase").
- **Sweep step two cancels `LOW_ENROLLMENT` at enrolled_count 1 < min_enrollment 2** — §3.9 verbatim; impl `services.py:489-494`. The cancellation-chain assertions (§3.9 verbatim) were untouched by Step 7 and pass.

**Per-edit pre-edit search log:** No edits were committed, so there is no per-edit log. The searches that produced the zero-edit conclusion, by subject:

1. *Creation-time min_enrollment ≤ capacity validation* — paths enumerated: `routes/sessions.py:51-91` (sole session-creation path); cross-read PRD §2.8 rung 3 and §3.2. Verdict: PRD pins verbatim; no silence.
2. *PATCH capacity/min_enrollment semantics (floor, check order, OCC)* — paths enumerated: `routes/sessions.py:119-151` (sole patch path); cross-read PRD §2.7, §2.8 rung 3, §3.2. Verdict: PRD pins verbatim, including the exact floor check and check order the fixture narrative cites.
3. *Waitlist promotion triggers* — paths enumerated: grep of `promote_waitlist` across all impl `.py` files (def at `services.py:235`; calls only at 287, 299, 472); `routes/sessions.py` patch path confirmed to contain no promotion call; `routes/registrations.py:44-95` create path confirmed to assign ENROLLED/WAITLISTED directly per §3.6 with no promote-first logic. Cross-read PRD §3.6, §3.8, §3.9, §2.10. Verdict: impl's trigger set equals PRD's enumerated trigger set; no silence exploited.
4. *Sweep step two + cancellation cascade* — paths enumerated: `services.py:437-502` (sweep) and `services.py:305-338` (`cancel_session_cascade`); cross-read PRD §3.9. Verdict: verbatim match; Step 7 left all cascade assertions untouched and they pass 76/76.

**Deliverable:** `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/workspace/PRD_FINALIZED.md` exists as a byte-identical copy of `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T16:53:58.425Z

## Summary

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1772_community_center_program_registration/workspace/PRD_COMPLETED.md`

**Source vs. output:** Source was `PRD_FINALIZED.md` (330 lines, 56,636 chars) → `PRD_COMPLETED.md` (336 lines, 61,298 chars). Delta: +6 lines, +4,662 chars. 17 edits (all in-paragraph inserts/revisions; no new sections).

**Counts:** 22 ambiguity-pins, 2 mismatch-revisions.

### Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)

- §2.1 — insert — ambiguity — list/read endpoints are role-gated only; ownership/identity checks apply solely to mutation paths (a HouseholdManager may read any household/participants/registrations) — implementation/routes/households.py:40-45 (pattern holds in all GET routes)
- §2.2 — insert — ambiguity — undefined path → `ERR_NOT_FOUND` (404); unsupported method on a defined path → `ERR_NOT_FOUND` (405); unexpected failure → `ERR_INTERNAL` (500) — implementation/app.py:58-70
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-range values clamped (limit into [1,100], offset floored at 0), not rejected — implementation/util.py:92-109
- §2.3 — insert — ambiguity — `created_at` ties break by insertion order (ids never consulted); same fallback in the §3 promotion selector, absence replay, and sweep queues — implementation/util.py:112-119, store.py:26-35
- §2.3 — insert — ambiguity — `has_more` true exactly when offset + page size < total_count — implementation/util.py:72
- §2.4 — insert — ambiguity — `version` starts at 1 at creation; `created_at`/`updated_at`/`api_request_timestamp` stamped from the logical clock — implementation/util.py:205-218, 28-29
- §2.5 — revise — ambiguity — clock settable to any instant (no monotonicity); malformed `to_iso8601` → `ERR_INVALID_REQUEST`; offset-less values read as UTC, bare dates become midnight UTC; response echoes the supplied string verbatim as `current_utc` — implementation/clock.py:16-20, routes/clock_routes.py:12-23
- §2.8 — insert — ambiguity — rung-3 range list gains `min_age` at least zero — implementation/routes/programs.py:48
- §3.1 — insert — ambiguity — date/instant inputs (`start_date`, `end_date`, `birth_date`) accept bare `YYYY-MM-DD` normalized to midnight UTC; age arithmetic compares calendar dates, ignoring time — implementation/util.py:32-45, services.py:56-59
- §3.1 — revise — ambiguity — program age corridor: `min_age` floor of zero pinned — implementation/routes/programs.py:48
- §3.1 — revise — mismatch — program creation outside DRAFT/PUBLISHED pinned to `ERR_SEASON_CLOSED` (CLOSED is the sole remaining season state; the prior `ERR_SEASON_NOT_PUBLISHED` claim never occurs in impl) — implementation/routes/programs.py:52-53
- §3.1 — insert — ambiguity — room PATCH naming the current status is not a toggle → `ERR_INVALID_STATE` — implementation/routes/rooms.py:60-62
- §2.8 — insert — ambiguity — session patch: supplied values must meet creation-time ranges; merged `min_enrollment` ≤ `capacity` validated against stored values after existence resolution; a no-field patch still succeeds and bumps version — implementation/routes/sessions.py:124-150
- §3.2 — insert — ambiguity — meeting creation is gated only by the season (session status does not gate it); meeting patch revalidates the merged `ends_at` > `starts_at` pair — implementation/routes/meetings.py:53-56, 90-106
- §3.3 — insert — ambiguity — `guarantee_min_cents`/`cancellation_guarantee_cents` non-negative (zero allowed); offering a contract is not season-gated — implementation/routes/contracts.py:59-62
- §3.4 — revise — mismatch — form rejection "attaching a `reason`" → reason accepted in the request but not persisted on the form — implementation/routes/safety_forms.py:127-137
- §3.5 — insert — ambiguity — `estimated_commitment_cents` non-negative (zero allowed) — implementation/routes/scholarships.py:168
- §3.5 — insert — ambiguity — denial `reason` likewise accepted but not persisted — implementation/routes/scholarships.py:195
- §3.7 — insert — ambiguity — payment `method` enum pinned to `EXTERNAL` or `ACCOUNT_CREDIT` — implementation/routes/registrations.py:49, 158
- §3.8 — insert — ambiguity — voiding a payment axis never clears `payment_due_at` — implementation/services.py:200-207, 291-299, 464-467
- §3.8 — insert — ambiguity — promotion selector's final tie fallback is insertion order; `waitlisted_at` is retained as history after promotion — implementation/services.py:245-254
- §3.9 — insert — ambiguity — a `registration_id` belonging to a different session → `ERR_NOT_FOUND`; attendance-mark creation is not gated on session status (four gates are exhaustive) — implementation/routes/attendance.py:60-65
- §3.9 — insert — ambiguity — ATTENDANCE_BASIS qualifying comparison is exact (2 × PRESENT-on-held ≥ meetings held), no percentage rounding — implementation/services.py:341-353
- §3.9 — insert — ambiguity — the sweep is not state-gated (runnable on DRAFT/PUBLISHED/CLOSED seasons; step 2 is a no-op unless PUBLISHED) — implementation/routes/seasons.py:123-129, services.py:474-475

**Notable finding driving the one true mismatch:** the PRD claimed program creation on a non-DRAFT/PUBLISHED season yields `ERR_SEASON_NOT_PUBLISHED`, but since CLOSED is the only other season state, the implementation only ever raises `ERR_SEASON_CLOSED` (routes/programs.py:52-53, and identically for sessions/meetings via the shared "same season gates" clause).
