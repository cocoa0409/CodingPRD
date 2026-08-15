# Worklog — task_1683_glider_club_soaring_operations

## Step 1: Create Task Directory — 2026-08-14T07:32:00.000Z

Task directory `tasks/task_1683_glider_club_soaring_operations/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-14T08:25:30.000Z

Clean. Final lint verdict block verbatim:

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     29
  Calls scanned (§1.8+§1.9):  457

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 + concurrency rules + domain constants (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 9 rules × 2 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, 9 sections

**Counts:**
- Entities: 11 (MembershipTier, Member, Aircraft, DutyRosterSlot, InstructorAvailability, Reservation, Flight, TowSlot, MaintenanceRecord, StudentProgress, RetrieveRequest)
- State machines: 9 (one per lifecycle entity except MembershipTier/MaintenanceRecord)
- Calculations: 7 (tow_fee, monthly_dues_posting, aircraft_currency_check, tow_slot_load, student_solo_eligibility, retrieve_cost_split, badge_level_recompute)
- Validations: 16 priority-ordered rows
- Endpoints: 59 (incl. `POST /soaring/_clock/set_current_utc` with the mandatory 2026-08-01T00:00:00Z default)
- Errors: 37
- Roles: 5 (ClubAdmin opaque; Member, DutyOfficer, Instructor, TowPilot entity_backed:Member)
- Concurrency rules: 2 OCC (TowSlot.version on flight posting; Aircraft.version on reservation create)
- Difficulty instances: 18 (every §0.5 rule × 2, all with structured `setup_api_calls`/`trigger` chains)
- Corner instances: 32 total (29 active test recipes + 3 `excluded_because` stubs referencing §1.8 instances)

**Notable design decisions:**
- **Archetype**: temporal windowing (primary) + ledger reconciliation (secondary); flat topology with cross-aggregate FKs and a self-referential `DutyRosterSlot.swap_with_slot_id`; peer-role RBAC with entity-backed ownership checks (slot owner, endorsing instructor).
- **Two distinct interval semantics** for Rule 8: half-open `[start,end)` on gliders (adjacency allowed) vs ±30-minute buffered windows for instructors (exactly-30-min gap allowed, 20-min rejected).
- **Dual-variant calcs on different domains**: provisional-vs-final tow fee on Flight (quota + non-discounted commenced-block surcharge, rounding order pinned: discount-then-add); forward-vs-prorated dues on Member with asymmetric rounding (floor on old-tier half, round_half_up on new-tier half, change-day billed to new tier). All formula-derived asserts are pre-computed literals (3420/4220, 4650, 7128, 11667/2333, 2700).
- **Depth-3 cascade** triggered by flight landing: hours accrual → in-request airframe ground at exactly 100.0h → future BOOKED reservations cancelled; depth-2 cascade from flight void: slot count decrement → slot auto-cancel when it hits 0 with future start.
- **Priority-conflict pairs**: state(5)-vs-fiscal(14) on payments to a RESIGNED member; safety(6)-vs-temporal(7) on checkout against a grounded glider outside the window.
- Lint clean on first full pass after fixing YAML quoting (unquoted `?` optionals and bracketed `grounds` flow items) and three FK reverse-reachability gaps (added `GET /soaring/instructor-availability/{id}`, `swap_with_slot_id?` and `retrieve_id?` list filters). No forbidden concurrency vocabulary; all 50 instance names unique across both design files.

## Step 3: Copy Shared Files — 2026-08-14T08:27:10.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1683_glider_club_soaring_operations/workspace/INSTRUCTION.md` (bash only, no subagent).

## Step 4: Generate PRD — 2026-08-14T08:58:30.000Z

PRD generation complete. Output written to `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/workspace/PRD.md`.

## Summary

**PRD line count:** 322 lines (ends at §5 Error Code Catalogue; no audit footer).

**Sections written:**
- §1 Introduction (3 paragraphs: club operations context, scope of the operational loop, `/soaring` mount and contract emphases)
- §2 Global Specifications — 11 subsections: 2.1 RBAC (with per-role `identity:` translation: `ClubAdmin` opaque; `Member`/`DutyOfficer`/`Instructor`/`TowPilot` entity-backed against `Member.id`), 2.2 verbatim fixed response-envelope block (byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Common Resource Properties (incl. the `MaintenanceRecord` exception: only `id` + `created_at`, no `updated_at`/`version`), 2.5 Logical Clock, 2.6 Member Account Ledger, 2.7 Rounding Discipline, 2.8 Airworthiness Currency, 2.9 Time Windows/Overlap/Buffers, 2.10 OCC (both rules, exact `occ_field` names + error IDs + HTTP 412, plus the "no other endpoint takes a version field" exclusivity clause), 2.11 Validation Order and Resource Lookup
- §3 Business Logic — 9 subsections (lifecycle-strategy grouping: tiers/enrollment → accounts/standing → fleet/grounding → reservations/checkout → tow slots/launch posting → landing/reconciliation/retrieves → instruction/progression → duty roster → ops-day close)
- §4 Endpoint table (4 columns; 59 rows = 59 scaffold endpoints)
- §5 Error catalogue (2 columns; all 37 error IDs)

**Coverage checks (all PASS):**
- Contract 1 Field-Name Coverage: `entities[].fields` 52/52 present, `endpoints[].input` 42/42 present, query params 0 required (scaffold folds them into `input`), path params 0 missing — **PASS** (two-pass: the first naive extraction was defeated by the §2.2 code fences shifting backtick pairing; re-ran with fenced blocks stripped)
- Contract 2 Rule Coverage: 54 targeted rule checks (both OCC rules with endpoint+field+error id; all 7 calculations with pinned rounding order — provisional-vs-final tow fee, asymmetric floor/half-up proration, strict-100.0-hour currency check with INSPECTION_OVERDUE tie-break, strict `<` capacity, 10.0h/90-day solo gate, marginal-band retrieve split with club residual conservation, badge rank order; all state transitions incl. cascade asymmetries like ground-vs-retire and suspend-vs-resign cancellation scopes; all 37 error IDs matchable in prose; validation priority order incl. the shared priority-12 pair) — **PASS**
- Contract 3 §3 Path Purity: 473 backticked tokens scanned, 0 path/method violations — **PASS**
- All 5 roles spelled exactly; all enum/state values present verbatim; §4 has 4 columns, §5 has 2 columns; payments-201 called out in the §4 status-code paragraph.

**Ambiguities resolved (from scaffold only, no external files read):**
1. The `Reservation` BOOKED→CHECKED_OUT transition names `ERR_OUTSIDE_RESERVATION_WINDOW`, which does not exist in the scaffold's error catalog; validation priority 7 maps the same checkout-window condition to `ERR_INVALID_TIME_WINDOW` (422). I used `ERR_INVALID_TIME_WINDOW`, treating the catalog as authoritative for error IDs.
2. Validation 7's "start_at >= now − grace" for reservation create: the only grace constant in the scaffold is the 15-minute `CHECKOUT_EARLY_GRACE_MIN`, so I rendered it as "start may not sit further than fifteen minutes in the past."
3. The complexity profile mentions a "badge expiry sweep" at ops-day close, but no state machine, calculation, or endpoint encodes badge expiry — per the no-invention rule I omitted it.
4. Retrieve band widths for routes shorter than band boundaries: expressed as clipped bands ("the first 50 kilometres — the whole route if shorter") consistent with the proportional-width allocation formula.

## Step 5: Generate Unit Tests — 2026-08-14T09:53:00.000Z

All audits pass. The work is complete.

## Summary

**Task**: task_1683_glider_club_soaring_operations — unit test generation from the two design indices against the PRD.

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/`)

**test_helpers/** (9 files):
- `types.py` — 11 entity TypedDicts + 15 status/role enums; `MaintenanceRecord` correctly modeled as append-only (no `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (47 endpoints)
- `api_errors.py` — `ApiErrorId` (37 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity structural assertions + `assert_member_balance`
- `factories.py`, `constants.py` — payload factories and PRD thresholds (tow ladder, 100.0h, fees, OCC fields, retrieve bands)
- `test_users.py` — shared opaque `ClubAdmin` constant + `make_<role>_headers(id)` builders for the four entity-backed roles
- `fixtures.py` — composite chains: `setup_ops`, `setup_checked_out`, `setup_in_flight`, `setup_reconciled_flight`, `complete_flight` (book→checkout→post→land→reconcile), OCC-aware raw posters, fresh-version getters; all ownership-gated calls thread real member ids
- `__init__.py` — barrel export

**test_suite/** (9 files): `conftest.py` + `test_01` members/tiers/payments (10 tests), `test_02` fleet/maintenance/grounding (6), `test_03` reservations (17), `test_04` flights/tow slots/fees (14), `test_05` instruction/progression (8), `test_06` duty roster (5), `test_07` retrieves (3), `test_08` security (2).

### Test counts
- **Queue A (Difficulty): 18/18 instances, 36 tests** (exactly 2 each)
- **Queue B (Corner): 29/29 non-stub instances, 30 tests** (`missing_auth_headers_rejected` gets a second header-variant test)
- **3 `excluded_because` stubs not translated**; cross-references verified to resolve to real queue-A instances

### Verification performed
- `pytest --collect-only`: 66 tests, no import errors
- Tag audit: every test ends with exactly one `Design:` line resolving to a real instance; no stubs translated; no shortfalls
- Citation audit: every docstring's quoted PRD text survives whitespace-normalized verbatim grep of `PRD.md`
- pyflakes clean (barrel re-exports excepted); no skip/xfail; no scaffold references

### Instances skipped
None beyond the 3 designed stubs — every non-stub instance passed the PRD-first two-condition filter.

### Assumptions made
1. **`version` initial value not pinned** — PRD §2.4 says "starts at its initial value" without naming 0 or 1, so assertions require only integer type (the corner instance's `version == 1` claim fails unique derivability).
2. **Logical clock set is unconditional** — PRD §2.5 describes the endpoint as setting/responding with `current_utc` with no monotonic constraint, so the solo-recency test legitimately sets the clock to 2026-05-01 (before the 2026-08-01 default) to age dual flights past the 90-day window.
3. **100.0h boundary instance** — per PRD §3.6 the 100.0h glider grounds in-request at landing (before the ops-day close); the test asserts the post-close end state, which is identical under either reading.
4. **Queue-A second tests** split each instance's asserted facets (primary numeric outcome vs. ledger/side-effect state), each rebuilding the full scenario since the runner restarts the server per test.

## Step 6: Generate Implementation — 2026-08-14T09:45:00.000Z

All checks pass and fresh-boot statelessness is confirmed (empty store, clock pinned at 2026-08-01T00:00:00.000Z). Implementation complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/workspace/implementation/`):
- `start.sh` — executable; guarded Flask install (`if ! python3 -c "import flask"`), `exec python3 app.py` in foreground
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — entry point, blueprint registration, envelope-consistent error handlers (ApiError, 404, 405, 500), binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory stores (dicts keyed by id), insertion sequence, logical clock pinned to `2026-08-01T00:00:00Z`, posted-months registry; **zero seeding**
- `errors.py` — all 37 catalog error IDs + `ApiError`
- `response.py` — exact envelope: `meta.api_request_id` (`req_…`), `meta.api_request_timestamp` (3-fractional-digit ISO, logical clock), `response_type`, `data`; pagination fields inside `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, 5-role recognition (400), role-permission gate (403)
- `util.py` — ISO 8601 parsing (Z/offsets/date-only), 3-digit UTC formatting, Decimal half-up helpers, limit/offset pagination (default 10/0, clamp 1–100), created_at-ascending stable sort
- `services.py` — calculations, currency checks, cascades, serializers
- `routes/`: `clockops.py`, `tiers.py`, `members.py`, `aircraft.py`, `availability.py`, `reservations.py`, `towslots.py`, `flights.py`, `duty.py`, `progress.py`, `retrieves.py`, `opsday.py`

**Endpoints implemented: 59** (all from the PRD §4 table, including `POST /soaring/_clock/set_current_utc` and `POST /soaring/ops-day/close`).

**State machines implemented (8):** Member (ACTIVE/SUSPENDED/RESIGNED with ARREARS auto-suspend at close + auto-reinstate on payment, manual suspend, resign cascades), Aircraft (AIRWORTHY/GROUNDED/RETIRED with three grounding routes — sweep, manual, in-request at landing — and maintenance-record restoration), Reservation (BOOKED/CHECKED_OUT/CLOSED/CANCELLED/NO_SHOW incl. late-cancel fee and close-driven NO_SHOW), Flight (IN_FLIGHT/LANDED/RECONCILED/VOIDED with void auto-cancelling empty future slots), TowSlot (SCHEDULED/CANCELLED with IN_FLIGHT block), DutyRosterSlot (ASSIGNED/CONFIRMED/COMPLETED/SWAP_PENDING/NO_SHOW/CANCELLED with full two-party swap handshake), InstructorAvailability (OPEN/CANCELLED), StudentProgress (PENDING/SIGNED_OFF/VERIFIED/REJECTED incl. rework loop).

**Calculation functions:** `tow_fee_calculation` (provisional + final variants: 4 altitude tiers, half-up discount step, included-tow monthly position over RECONCILED flights, 400-cent per-commenced-30-min-block surcharge beyond 60 min, never discounted), `monthly_dues_posting` (forward first-close-of-UTC-month + prorated blend with floored old half / half-up new half, change day billed to new tier), `aircraft_currency_check` (strict <100.0 h via exact `Fraction` arithmetic, strict annual-due comparison, INSPECTION_OVERDUE wins ties), `tow_slot_load` (strict capacity <, void decrement + auto-cancel), `student_solo_eligibility` (10.0 dual-hour cumulative threshold + 90-day recency gate), `retrieve_cost_split` (ceil-km total, proportional band allocation rounded per band, pilot = band1 + half of band2, club residual), `badge_level_recompute` (A<B<C<BRONZE<SILVER).

**Validation ordering:** auth headers (400) → role permission (403) → existence left-to-right (404) → OCC preconditions (`expected_aircraft_version`/`expected_tow_slot_version`, 412) → target state (409 family with exact IDs) → member standing (ERR_MEMBER_NOT_ACTIVE / ERR_INSTRUCTOR_NOT_ACTIVE) → airworthiness incl. inline currency (409) → time windows (422) → glider overlap (half-open, touching OK) → instructor 30-min buffer (gap exactly 30 allowed) → availability coverage → tow capacity → tow-slot coherence / retrieve landed-out → swap integrity → credit cap (402) → referential/enum integrity last (422). Ownership rules enforced per role (Member=self, TowPilot=slot's pilot on posting, Instructor=own windows/records, duty-slot owner errors as ERR_NOT_SLOT_OWNER 403). Every mutation — including cascades — refreshes `updated_at` and bumps `version`; `MaintenanceRecord` carries only `id`/`created_at`.

**Smoke-test result:** boot via `bash start.sh` clean; two scripted end-to-end flows passed — (1) clock set, tier/member/aircraft creation, unique-constraint 409, stale-version 412s, half-open overlap, checkout window, provisional fee (3420c), landing with included-tow quota + surcharge (final 800c for 95 min), balance delta, reconcile→CLOSED, retrieve split at 75 km (pilot 11667c / club 2333c), duty confirm, ops-day close (dues_posted_count=2, roster finalized, second close idempotent); (2) mid-month proration (9458c pending swept instead of forward dues), arrears auto-suspend at 25000c + auto-reinstate via payment, credit-cap 402, annual-overdue grounding cascade restoring via ANNUAL record, solo-signoff 422 eligibility gate, swap propose/accept exchange, void→slot auto-cancel with reservation left CHECKED_OUT. Fresh reboot verified: empty store, clock re-pinned — safe for `--isolation per-test-server`.

## Step 7: Run Tests and Iterate — 2026-08-14T10:20:00.000Z

All 8 rounds pass 66/66 with zero failures and zero errors. Clean sweep — exiting.

## Summary

- **Iterations run:** 3 eight-round parallel sweeps (sweep 1: 13 failing; sweep 2: 2 failing; sweep 3: 66/66 passed in all 8 rounds).

- **Tests deleted:** none. Every failing assertion traced to a verbatim PRD rule; no PRD-silence or unique-derivability collapses found.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/test_helpers/fixtures.py` — default `clock` parameter of `setup_checked_out`, `setup_in_flight`, and `setup_reconciled_flight` changed from `2026-08-10T10:00:00Z` to `2026-08-10T09:10:00Z`. The default `res_start` (09:00) sat 60 minutes in the past at booking time, violating PRD §3.4 ("`start_at` may not sit further than fifteen minutes in the past"); the latent default is now compliant (10-minute gap).

- **Fixes applied to `test_suite/` (all STEP 2 test bugs — setups violated the PRD §3.4 15-minute past-window precondition, so the PRD-faithful implementation correctly rejected booking with `ERR_INVALID_TIME_WINDOW`):**
  - `test_03_reservations.py::TestResignBlockedInFlight` — clock `10:00` → `09:40` (was 30 min past `res_start` 09:30).
  - `test_04_flights_and_tow_slots.py` — clock adjustments in 7 setup blocks so `start_at` is 10 (not 30) minutes in the past: `TestProvisionalVsFinalTowFee._setup_and_fly` (14:00→13:40), `TestTowSlotCapacityBoundary._setup_full_slot` (10:00→09:40), `TestFlightVoidCascade._setup_in_flight_flight` (10:30→10:10), `TestPostThenVoidBalanceInvariant._ctx` (10:00→09:40), `TestFlightLifecycleErrors` both tests (10:00→09:40), `TestFlightPostingOCC` (10:00→09:40), `TestImmediateConsistency` (10:00→09:40). All downstream takeoff/landing timestamps and every assertion preserved.
  - `test_04_flights_and_tow_slots.py::TestTowSlotCapacityBoundary` — fixed an f-string typo producing the malformed timestamp `2026-08-20T10:010:00Z` for i=1 (`10:0{5+i*5}` → `10:{5+i*5:02d}`), which the implementation correctly rejected with `ERR_REFERENTIAL_INTEGRITY`.
  - Stale comment updated in `test_void_to_zero_auto_cancels_future_slot` (clock reference).

- **Fixes applied to `implementation/`:** none. The implementation was PRD-faithful on every tripped rule (15-minute booking window per §3.4, ISO 8601 validation per §2.11); all 13+2 failures were test-side precondition violations.

All failures were deterministic across all 8 rounds (no flakiness observed); final state verified as 66/66 passed in each of the 8 concurrent rounds.

## Step 8: Finalize PRD — 2026-08-14T10:28:00.000Z

All verification is complete. No edits qualified — `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

## Summary

**Line counts / delta:** `PRD.md` = 322 lines; `PRD_FINALIZED.md` = 322 lines; 0% delta (identical copy). File: `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/workspace/PRD_FINALIZED.md`

**Changes:** none. Every Step 7 fix was a test-side precondition repair (fixture/test clocks moved inside the booking window, one f-string timestamp typo, one stale comment) against rules the PRD already pins; there were zero `implementation/` fixes and zero test deletions, so no PRD silence or PRD/impl mismatch was revealed.

**Candidate edits evaluated and rejected (pre-edit search log):**

1. **§3.4 booking-window boundary (PRD line 156: "`start_at` may not sit further than fifteen minutes in the past")**
   - (a) Subject: inclusive-vs-exclusive boundary at exactly 15 minutes past, and which clock "the past" is measured against.
   - (b) Impl paths enumerated: `implementation/routes/reservations.py:93-94` (booking create: `at = db.now()`; rejects iff `start_at >= end_at or start_at < at - timedelta(minutes=15)` — exactly 15 minutes past passes); `implementation/routes/reservations.py:224` (checkout window, same `CHECKOUT_EARLY_GRACE_MIN = 15` constant from `implementation/services.py:25`, inclusive `[start_at-15min, end_at]`); `implementation/services.py:244,252,268` (other "future"-relative comparisons, unrelated to this rule); PRD §2.5 line 90 (logical clock governs every temporal rule, explicitly naming "now" and "windows"); PRD §2.9 line 108 (checkout window prose). Cross-checked PRD's own boundary conventions: inclusive limits are always flagged explicitly ("at or above the 20,000-cent threshold" line 138, "exactly 100.0 hours fails" line 104, "a gap of exactly 30 minutes is allowed" line 156).
   - (c) No wording change committed: "further than fifteen minutes in the past" admits only the strict reading (> 15 min fails, == 15 min passes), which is exactly what the impl computes, and §2.5 already fixes the clock. Any "clarifying" edit would risk re-scoping a sentence that is already consistent with every enumerated path.

2. **§2.11 malformed ISO 8601 input → `ERR_REFERENTIAL_INTEGRITY` (the `TestTowSlotCapacityBoundary` typo site)**
   - (a) Subject: error code for an unparseable datetime string (`2026-08-20T10:010:00Z`).
   - (b) Impl paths enumerated: `implementation/util.py:17-38` (`parse_dt` raises `ERR_REFERENTIAL_INTEGRITY` 422 on `ValueError` from `fromisoformat` and on non-string input; bare dates coerced to 00:00Z, `Z` suffix normalized); all callers via `need_dt` (`util.py:127-128`); PRD §2.11 line 122 ("enum/type referential integrity is checked last (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422)"); PRD §5 error catalogue lines 284-322 (no other validation-type error code exists — no `ERR_VALIDATION`/400 alternative is defined).
   - (c) No wording change committed: a malformed datetime is a type violation under §2.11's existing "enum/type referential integrity" clause, and the §5 catalogue offers no competing code, so the impl behavior is already uniquely determined. Adding a sentence about malformed timestamps would be a new (unscoped) claim not traceable to any Step 7 failure — the typo fix was a pure test bug.

## Step 9: Complete PRD — 2026-08-14T10:49:00.000Z

The patch is complete and structurally minimal. Final verification passed: same section count (22 headings), endpoint table and error catalogue untouched, only in-paragraph inserts/revisions plus one new paragraph in §2.1.

## Summary

**Source:** `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/workspace/PRD_FINALIZED.md` (322 lines / 48,628 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1683_glider_club_soaring_operations/workspace/PRD_COMPLETED.md` (324 lines / 54,335 chars). Char delta: **+5,707** (net; +5,624 content plus 2 newlines). No new sections; all edits are in-paragraph except one new paragraph in §2.1.

**Counts:** 29 ambiguity-pins, 4 mismatch-revisions (33 edited passages total).

**Changes:**

- §2.1 — insert — ambiguity — ownership violations by a permitted role acting on another member's resource (pay/resign/book/checkout/cancel/land/retrieve-file for Member, availability publish/cancel for Instructor, slot schedule/launch-post for TowPilot) rejected with `ERR_FORBIDDEN_ROLE` (403) — middleware.py:37-38; members.py:117-118,162-164; reservations.py:61-62,196-197,239-240; availability.py:38-39,85-86; towslots.py:41-42; flights.py:73-76,181-182; retrieves.py:46-47
- §2.3 — insert — ambiguity — limit clamped into [1,100], offset clamped to >=0, unparseable values fall back to defaults — util.py:144-156
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order — util.py:168-170
- §2.4 — revise — ambiguity — `version` starts at **1** on creation — tiers.py:63, members.py:65, aircraft.py:72
- §2.5 — insert — ambiguity — clock may be set to any instant, forward or backward, without validation — clockops.py:18-20
- §2.6 — revise — **mismatch** — pending dues are swept only at the next dues-posting close (first close of a UTC month), not any next close — opsday.py:32-47
- §2.10 — revise — ambiguity — missing or non-integer OCC field fails identically to stale (412); other endpoints ignore a supplied version field — reservations.py:76-85, flights.py:78-87
- §2.11 — insert — ambiguity — OCC checks placed immediately after existence, before state gates — reservations.py:76, flights.py:78
- §3.1 — insert — ambiguity — out-of-range `tow_fee_discount_pct` and negative/non-integer `included_tows_per_month` draw `ERR_REFERENTIAL_INTEGRITY`; uniqueness checked after field validation — tiers.py:36-53
- §3.1 — revise — **mismatch** — prorated charge swept at next dues-posting close (first of month), replacing that month's forward debit — opsday.py:38-41
- §3.2 — insert — ambiguity — `amount_cents` is any integer; no positivity bound — members.py:126-133
- §3.2 — insert — ambiguity — manual suspend valid only from `ACTIVE`, else `ERR_INVALID_STATE` — members.py:150-154
- §3.2 — revise — ambiguity — resignation allowed from `ACTIVE` or `SUSPENDED`; re-resigning a `RESIGNED` member fails `ERR_INVALID_STATE` — members.py:166-170
- §3.3 — revise — ambiguity — `notes` stored null when omitted; `REPAIR` records alter no airframe field and never restore; `INSPECTION_100H`/`ANNUAL` always refresh airframe `updated_at`/`version` — aircraft.py:175-204
- §3.3 — revise — ambiguity — manual ground valid only from `AIRWORTHY`, else `ERR_INVALID_STATE` — aircraft.py:104-107
- §3.3 — revise — ambiguity — unground requires `GROUNDED` + `MANUAL`, else `ERR_INVALID_STATE` — aircraft.py:117-121
- §3.3 — revise — ambiguity — retire requires `AIRWORTHY` (checked before the CHECKED_OUT scan), else `ERR_INVALID_STATE` — aircraft.py:133-145
- §3.4 — revise — ambiguity — availability coverage is inclusive at boundaries (window endpoints coinciding with the span cover it) — reservations.py:130-135
- §3.4 — revise — **mismatch** — late-cancel fee applies to any endpoint cancel regardless of acting role (not only member-initiated), strictly inside 24h — reservations.py:246-253
- §3.5 — revise — ambiguity — tow-slot creation performs no window-ordering or airworthiness validation; `capacity` < 1 → `ERR_REFERENTIAL_INTEGRITY` — towslots.py:59-60
- §3.5 — revise — ambiguity — tow-slot cancel requires `SCHEDULED` first, else `ERR_INVALID_STATE` — towslots.py:102-111
- §3.5 — revise — ambiguity — `release_altitude_ft` < 500 → `ERR_REFERENTIAL_INTEGRITY` (422); `takeoff_at` window inclusive of both slot endpoints — flights.py:117,124-128
- §3.5 — revise — ambiguity — provisional fee uses the member's tier as it stands at posting — flights.py:129-130
- §3.6 — revise — ambiguity — final fee reads the member's tier as it stands at landing (both `included_tows_per_month` and discount) — flights.py:197-198, services.py:110-123
- §3.6 — revise — **mismatch** — dual-hour accumulator grows for dual flights regardless of the pilot's tier (dropped "pilot is on a student tier") — services.py:168-179, flights.py:229-245
- §3.6 — revise — ambiguity — retrieve `distance_km` positivity check (422) fires before the landed-out gate (local §2.11 exception); band widths measured against raw unrounded distance; `retrieve_id` back-reference persists after retrieve cancellation — retrieves.py:48-62,151-163; services.py:143-148
- §3.6 — revise — ambiguity — retrieve cancel from non-`REQUESTED` → `ERR_RETRIEVE_NOT_REQUESTED` — retrieves.py:156-160
- §3.7 — revise — ambiguity — availability publish applies no window-ordering validation; cancelling a non-`OPEN` window → `ERR_INVALID_STATE` — availability.py:29-60,87-90
- §3.7 — revise — ambiguity — opening `Instructor` need not be the endorsing instructor — progress.py:49-75
- §3.7 — revise — ambiguity — solo recency boundary inclusive (takeoff exactly 90 days earlier qualifies); dual-hours snapshot taken on every successful signoff regardless of kind — services.py:194-197; progress.py:139-141
- §3.7 — revise — ambiguity — return-for-rework on non-`SIGNED_OFF` → `ERR_PROGRESS_NOT_SIGNED_OFF`; reject on non-`PENDING` → `ERR_PROGRESS_NOT_PENDING` — progress.py:176-199
- §3.8 — revise — ambiguity — `duty_date` time-of-day truncated to 00:00Z — duty.py:46-49
- §3.8 — revise — ambiguity — propose-swap requires origin `ASSIGNED` (`ERR_INVALID_STATE`, checked before target gates); accept/decline invoked on the **originating** slot's id; accept by non-target-owner or with no swap partner → `ERR_NOT_SLOT_OWNER`, origin not `SWAP_PENDING` → `ERR_INVALID_STATE`, target no longer `ASSIGNED` → `ERR_SWAP_INVALID` — duty.py:103-205
- §3.9 — insert — ambiguity — a `duty_date` counts as past only when strictly before the logical clock's current calendar day; same-day slots are not finalized — opsday.py:81

**Key findings:** The four true mismatches were (1-2) `pending_dues_cents` sweeping only on dues-posting (first-of-month) closes rather than "the next ops-day close" as PRD stated in §2.6/§3.1 (opsday.py gates the sweep inside the `POSTED_MONTHS` branch); (3) the late-cancel fee applying to DutyOfficer/ClubAdmin endpoint cancels too, not just "member-initiated" ones; (4) dual-hour accumulation ignoring the student-tier qualifier §3.6 stated. Everything else was PRD silence pinned to impl behavior.
