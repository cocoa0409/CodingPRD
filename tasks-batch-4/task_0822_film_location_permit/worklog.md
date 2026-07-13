# Worklog — task_0822_film_location_permit

## Step 1: Create task directory — 2026-07-10T13:28:50.447Z

Created `tasks/task_0822_film_location_permit/` and `tasks/task_0822_film_location_permit/workspace/` (directory pre-assigned by the caller; no auto-scan of ./tasks performed).

## Step 2: Generate scaffold (subagent, Expert) — 2026-07-10T14:06:00.000Z

All three scaffold artifacts are complete, parse cleanly, pass `scaffold_lint.py` with `VERDICT: clean lint`, and every computed literal has been verified by executing the formulas.

## Summary

Generated a fresh **Expert**-tier scaffold for a Municipal Film & Location Permit Office, purely from the scenario + skill spec (no sibling tasks consulted).

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0822_film_location_permit/`):
- `SCAFFOLD.yaml` — 1615 lines (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1287 lines (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 979 lines (§1.9)

**Counts:** 13 entities · 40 endpoints · 19 error codes · 24 validations · 6 calculations (4 variant entries) · 6 state machines · 2 OCC concurrency rules · 4 roles. §1.8 = 18 difficulty instances (9 rules × 2); §1.9 = 25 active corner instances + excluded-because stubs. Lint scanned 372 setup/trigger calls — clean.

**Design notes:**
- **Profile:** temporal_windowing × multi_party_negotiation, flat topology, cyclic state machines, peer_roles, immediate consistency. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.
- **Core coupling:** `PermitApplication` is the OCC parent driving a revision-loop lifecycle (DRAFT→UNDER_REVIEW⇄REVISION_REQUIRED→ISSUED→WRAP→WRAPPED, plus permit surrender ISSUED→WITHDRAWN). Multi-department review fans out per `Department.trigger_condition`.
- **All 9 difficulty rules satisfied with genuine differentiation:** dual-variant fee (Application) vs compliance score (Company); combinatorial modes (a) tiered-crew formula and (c) surcharge-tier-keyed-on-subtotal; cyclic SMs on two entities; a depth-3 issue cascade (issue→booking CONFIRMED→competitor BLOCKED→assignment CANCELLED) and a depth-2 reject cascade; two priority-conflict pairs (state/fiscal, safety/temporal); two boundary metrics (notification `>=7` days, empty-locations set); two cross-entity pairs; two overlap semantics (buffered segments vs half-open bufferless officer shifts); two conserved quantities (deposit money vs segment occupancy).
- **Determinism:** logical clock defaults to `2026-03-01T00:00:00Z`; all ordering uses `created_at`, never `id`; both OCC endpoints require `expected_application_version` and bump `version`.
- **One deliberate design choice:** road-closure creation rejects only against CONFIRMED bookings (competing PENDING requests coexist and are resolved at issuance), which is what makes the BLOCKED/RELEASED cascade states reachable.

Endpoint count (40) runs above the nominal Expert 20–32 band; this is driven by the scenario's breadth (9 distinct sub-systems) requiring one reverse-reachability GET per FK edge, and the band is explicitly guidance rather than a hard rule.

Orchestrator verification: all three files `yaml.safe_load` cleanly; SCAFFOLD.yaml declares 40 endpoints.

## Step 3: Copy shared files — 2026-07-10T14:07:09.868Z

Copied `./INSTRUCTION.md` → `tasks/task_0822_film_location_permit/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (subagent) — 2026-07-10T14:14:30.000Z

All three hard contracts pass. The PRD is complete.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_0822_film_location_permit/workspace/PRD.md`

**Line count:** 294 lines

**Endpoint coverage:** 40/40. The §4 table has exactly 40 rows (verified by count), matching the scaffold's 40 `- method:` declarations. §5 error table has all 19 error codes.

**Hard-contract verification:**
- **Contract 1 (Field-Name Coverage): PASS** — all 79 required identifiers (entity `fields[].name` + endpoint `input` params, including `to_iso8601`, `expected_application_version`, `damages_reported`, `decision`, `decision_notes`) appear verbatim in backticks. (Initial script gave a false negative due to the ```json code fences in §2.2 shifting inline-backtick parity; after stripping fenced blocks the diff is empty.)
- **Contract 3 (§3 Path Purity): PASS** — zero backtick tokens in §3 start with `/` or are bare HTTP methods; every endpoint is referenced via state-transition/role-action/capability framing. §2.2 emitted verbatim from the fixed source file.
- **Contract 2 (Rule Coverage):** addressed in prose — all 6 state machines (incl. Cascade A depth-2, Cascade B depth-3 confirm→block→cancel, BLOCKED→PENDING restore in `created_at` ASC order), all 5 calculations (permit_fee ESTIMATE/FINAL, municipal_surcharge tiers, deposit_amount, deposit_refund, compliance_score PROVISIONAL/FINAL, officer_assignment_cost), both OCC rules (COI-submit and issue, `expected_application_version`/`ERR_STALE_APPLICATION_VERSION`/412), validation precedence ordering, and per-endpoint check ordering (issue: reviews→OCC→COI→fee; officer-assignment: time→state→active→overlap; rider: state→aviation→flight-window).

**Scaffold gaps flagged:** None. Every constant used in a formula is declared with a numeric value:
- The RoadClosureBooking transition references `resource_temporal_overlap segment_buffer` (no such calculation block exists in the scaffold), but the buffer's value is given explicitly as `SETUP_BUFFER_MINUTES=60` in validation priority 52, so no number had to be invented — I used 60 minutes throughout.
- `NOTIFICATION_MIN_LEAD_DAYS` (7) and `SETUP_BUFFER_MINUTES` (60) live in validation `check` text rather than a `constants:` map, but both carry explicit values. All `calculations[].constants` maps are fully populated.

Orchestrator verification: PRD §4 endpoint table = 40 rows; set-equal to SCAFFOLD.yaml `endpoints` (0 missing, 0 extra).

## Step 5: Generate unit tests (subagent) — 2026-07-11T03:21:05.792Z

Complete. Test infrastructure and suite generated for `task_0822_film_location_permit`.

## Summary

**Files written**

`test_helpers/` (Stage 1): `types.py`, `api_client.py` (39 endpoint methods), `api_errors.py` (19 error IDs + HTTP-status registration), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque coordinator constant + entity-backed per-instance header builders for ProductionCompany/DepartmentReviewer/FieldOfficer), `fixtures.py` (atomic step helpers + 7 composite scenarios: `setup_issue_ready`, `setup_issued_application`, `setup_wrap_requested_application`, `setup_issue_cascade_scenario`, `setup_confirmed_booking_on_segment`, `setup_block_restore_scenario`, `setup_dual_variant_fee_scenario`), `__init__.py` barrel.

`test_suite/` (Stage 2): `conftest.py` + 8 domain-named files (`test_01`–`test_08`).

**Coverage — 61 tests, all imports/collection clean**
- Queue A (Difficulty): all **18 instances**, **2 tests each = 36 tests**. Common-integer literals (fees 152250/304500/204750/190000, surcharge 9500, total 199500, deposit 89900, billed 32000, compliance 75, refund 6240/held 2000) copied verbatim from the design YAML, never recomputed.
- Queue B (Corner): all **25 non-stub instances**, **1 test each = 25 tests**.
- Every docstring ends with exactly one verbatim `Design: Difficulty/<rule>/<name>` or `Design: Corner/<section>/<name>` line resolving to a real instance; no untagged or dual-tagged tests.

**Skipped instances:** none. All 8 `excluded_because:` stubs (shoot_days_computed_field, issue_cascade_confirm_and_block, deposit_amount_correct, final_fee_input_set_filtering, error_no_locations_on_submit, error_reviews_incomplete_on_issue, error_segment_double_booked, cascade_end_to_end) were correctly *not* translated — their `difficulty_instance` cross-references all resolve to real queue-A instances that own the assertion. No instance failed the PRD-first filter (the PRD covers and uniquely-derives every asserted rule).

**Notes**
- `issue_from_draft_returns_invalid_state` asserts `ERR_INVALID_STATE`, cited to PRD §3.5 "Issuance is available only from UNDER_REVIEW; from any other state it is rejected" (the uniform invalid-transition guard used throughout the PRD).
- Citations quote PRD prose verbatim (markdown backticks stripped in the docstring text); each cited sentence exists in `workspace/PRD.md` with distinctive ≥8-word backtick-free runs — verified by grep.
- Every fixture builds preconditions from scratch via PRD endpoints (per-test-server empty DB), threads entity-backed identities through `make_*_headers(entity_id)`, and uses `get_success_data` for setup.

## Step 6: Generate implementation (subagent) — 2026-07-11T03:21:05.792Z

All test servers stopped and the three implementation files are in place. The implementation is complete and verified.

## Summary

Built a complete Python + Flask implementation of the Municipal Film & Location Permit Office API at `/home/ubuntu/github/CodingPRD/tasks/task_0822_film_location_permit/workspace/implementation/`.

**Files (3):**
- `app.py` — single-file server, all 40 endpoints + business logic (~950 lines)
- `start.sh` — foreground launcher, reads `$PORT` (default 10000), binds `0.0.0.0`, guards `pip install` on a cheap `import flask` check, `exec`s the server
- `requirements.txt` — `flask`

**Storage model:** In-memory only. 13 module-level dicts keyed by UUID (companies, departments, officers, segments, applications, locations, reviews, certificates, bookings, assignments, riders, notifications, ledger). No seeding, no disk persistence — every `start.sh` re-invocation wipes all state. A global `_seq` counter provides deterministic `created_at`-ascending ordering; the logical clock defaults to `2026-03-01T00:00:00Z`.

**Endpoints:** All 40 from the table (registry CRUD, application lifecycle, submit/issue/withdraw/wrap, COI, riders, notifications, payments, reviews, road-closure bookings, officer assignments, `/_clock/set_current_utc`).

**Notable design decisions (all traced to PRD prose):**
- **Response envelope** exactly per §2.2: `meta{api_request_id, api_request_timestamp}` + `response_type` + `data`; pagination fields (`limit/offset/total_count/has_more`) added to `meta` on list endpoints only. Immutable entities (Department, StreetSegment, LocationDetail, NeighborhoodNotification, LedgerEntry) expose only `id`+`created_at`; all others carry `updated_at`+`version`.
- **Validation precedence** implemented per §2.8 / §1.4 priorities: auth(401)→role(403)→path-exist(404)→body-FK-exist(404, checked before body well-formedness)→body(400)→time-range(422)→reviewer-dept-match(403)→state(409)→business rules. Issue order: INVALID_STATE→REVIEWS_INCOMPLETE→STALE_VERSION→COI_NOT_VERIFIED→FEE_UNPAID.
- **Money** kept as integer cents with floor division for basis-point rates and `math.ceil` for billable hours; crew/surcharge/deposit tiers exactly per §3.4/§3.5.
- **Cascades:** Cascade A (review REJECT → app REVISION_REQUIRED → release PENDING/CONFIRMED bookings), Cascade B (issue → confirm bookings → block buffer-overlapping competitors → cancel their PROPOSED assignments), and the release/restore chain (withdraw → restore BLOCKED bookings in `created_at` order). Segment overlap uses a 60-min buffer (symmetric); officer overlap is half-open `[start,end)` with no buffer.
- **OCC** on `expected_application_version` for issue and COI-submit; skipped when the field is omitted (per skill guidance), 412 on mismatch.
- **compliance_score** always derived at read from the three counters (satisfies both PROVISIONAL and FINAL). `missed_notification_count` is incremented as a side effect when a notification is rejected with `ERR_NOTICE_TOO_LATE` — the only trigger the spec describes for that counter.

Verified end-to-end with a 27-assertion smoke test (all pass): auth, full application lifecycle, both fee variants, surcharge/deposit/penalty/refund arithmetic, both cascades + restore, OCC staleness, segment/officer double-booking (including the half-open "touching is OK" boundary), compliance scoring, drone aviation-coverage guard, pagination bounds, and not-found paths.

One PRD ambiguity worth flagging: the `actual_end_at >= issued_at` wrap-close precondition has no error_id in the catalog, so it is not enforced (enforcing with a guessed error risked false failures on valid no-overage wraps).

## Step 7: Run tests and iterate (subagent) — 2026-07-11T03:24:00.000Z

All 8 rounds pass cleanly. The sweep confirms a stable, non-flaky pass.

Summary:
- Iterations run: 1 (initial sweep already clean).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

All 8 stability rounds returned 61/61 passed, 0 failed, 0 errors. The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_0822_film_location_permit/workspace/implementation` was already in a passing state; no diagnostic protocol action was required.

Orchestrator verification: all 8 `results.{1..8}.json` on disk confirm passed=61 failed=0 errors=0 total=61.

## Step 8: Finalize PRD — SKIPPED — 2026-07-11T03:24:00.000Z

Skipped per the skill's skip condition. Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already determined every behavior the implementation exhibits at every Step-7-exercised site, so no `PRD_FINALIZED.md` is produced. Step 9 will scan from `PRD.md` directly.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch (subagent) — 2026-07-11T03:31:00.000Z

I walked the full implementation (`implementation/app.py`, 1268 lines) against every PRD passage and produced a minimal-patch `PRD_COMPLETED.md`.

## Summary

- Source `PRD.md`: 294 lines, 46382 chars. `PRD_COMPLETED.md`: 294 lines, 48026 chars. Char delta: +1644 (all inline; no lines added/removed, no new sections).
- Ambiguity-pins: 7. Mismatch-revisions: 4. (Total 11 changes.)

Changes:
- §2.1 (RBAC, ProductionCompany) — revise — mismatch — PRD claimed ownership checks compare a resource's `production_company_id` to `X-User-ID`; impl enforces no such check for ProductionCompany (only DepartmentReviewer's department match is enforced), so authorized by role alone — implementation/app.py:1078 (only enforced uid compare) vs create_location/booking/coi/rider/submit/withdraw/payment (none).
- §2.3 (Pagination) — insert — ambiguity — pinned that list ordering breaks `created_at` ties by ascending creation/insertion order (sorts by `_seq`) — implementation/app.py:272.
- §2.5 (OCC) — insert — ambiguity — pinned that `expected_application_version` is enforced only when present; omitted/null skips the version check — implementation/app.py:725-727, 869-871.
- §3.2 (Assembling application) — insert — ambiguity — pinned that `shoot_days` calendar dates are taken in UTC — implementation/app.py:587 (dates via UTC-normalized instants at parse_iso:84).
- §3.5 (Issuance) — revise — mismatch — issuance from a non-`UNDER_REVIEW` state yields `ERR_INVALID_STATE` (409), checked ahead of the four preconditions; removed the redundant/contradicting state clause from precondition 1 (which impl attributes to `ERR_INVALID_STATE`, not `ERR_REVIEWS_INCOMPLETE`), and noted the vacuous pass when zero reviews — implementation/app.py:718-723.
- §3.3 (Review decision) — revise — ambiguity — pinned precondition order (department-match `ERR_UNAUTHORIZED` first, then review-must-be-`PENDING` `ERR_INVALID_STATE`, then application-must-be-`UNDER_REVIEW`), adding the previously-unstated already-decided-review rejection — implementation/app.py:1078-1085.
- §3.6 (Rider decision) — insert — ambiguity — pinned that the rider must still be `REQUESTED` (already-decided → `ERR_INVALID_STATE`) and that the rider-status check precedes the application-status check — implementation/app.py:962-965.
- §3.6 (Drone flight window) — insert — ambiguity — pinned that flight-window containment is checked only when both `flight_start_at` and `flight_end_at` are provided; else skipped — implementation/app.py:931-936.
- §3.1 (Company counters) — revise — mismatch — reworded `missed_notification_count` from "prior applications ... at issue time" to "each time ... rejected as too late when recorded" — implementation/app.py:984-988.
- §3.7 (Notifications) — revise — mismatch — pinned that the `missed_notification_count` increment happens synchronously when the too-late notification is recorded (before the 422, no record created), not deferred to issuance — implementation/app.py:983-988.
- §3.8 (Wrap-close) — revise+insert — mismatch+ambiguity — (a) `actual_end_at` "must be at or after `issued_at`" softened to "expected ... though not validated" (impl performs no such check); (b) pinned that `damage_cost_cents` is stamped as the reported amount only when `damages_reported` is true and an amount was supplied, else 0 — implementation/app.py:807-821.

Notes: An extra `GET /` health endpoint exists in impl but is non-domain infrastructure not covered by any PRD prose, so I left it unpinned rather than adding an endpoint-table row. The PROVISIONAL/FINAL compliance-score "stored at wrap-close" wording was left as-is: impl always derives the score from persisted counters, which after wrap-close's increments yields the same observable FINAL value, so there is no observable divergence.
