# Worklog — task_0945_adaptive_inclusive_recreation

Scenario (verbatim): `945. Adaptive & Inclusive Recreation Program: participant intake & ability/support-need, activity & 1:1 support staffing, adaptive-equipment inventory, transportation, scholarship/waiver funding, caregiver & consent, progress/goal, reporting`

Difficulty: **beyond-Expert** (user request: "generate task hard than expert level!")

## Step 1: Create task directory — 2026-08-09T10:13:40.000Z

Created `tasks/task_0945_adaptive_inclusive_recreation/` and `workspace/`.

## Step 3: Copy INSTRUCTION.md — 2026-08-09T10:13:45.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (done early, out of order; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-09T11:19:00.000Z

Scaffold generated at `/home/ubuntu/github/CodingPRD/tasks/task_0945_adaptive_inclusive_recreation/` (3 files, 9,596 lines).

### Counts

| Metric | Value | Target |
|---|---|---|
| Entities | **21** | 18–21 ✓ |
| Endpoints | **90** | 76–90 ✓ |
| Error codes | **70** | 58–72 ✓ |
| Calculations | **19**, of which **10 dual-variant** | 12+ / 9+ ✓ |
| Status axes (state machines) | **16**, of which **13 non-linear** | 9+ / ≥5 ✓ |
| Ladder rungs | **60** — 1 global write gate (rung 9) + 6 ordered sub-gates (34 consent, 37 assessment, 45 capacity, 49 equipment, 52 transport, 56 funding) | 45–60 / 1 / 3+ ✓ |
| OCC rules | **5** (session, participant, funding source, equipment item, transport run) | 3+ ✓ |
| Conservation invariants | **5** (slots, 1:1 pool, funding cents, transport positions, pooled units) | 4+ ✓ |
| Max cascade depth | **8** (withdraw → slot freed → promotion → encumbrance → ledger → EXHAUSTED → award lapse → demotion) | ≥6 ✓ |
| Declared constants | **31**, **0 undeclared** | 0 ✓ |
| §1.8 instances | **22** (2–3 per rule, all 9 rules) | ≥18 ✓ |
| §1.9 instances | **50 non-stub + 11 `excluded_because` stubs** | — |

### Validation results
- `yaml.safe_load`: **OK** for all three files.
- `scaffold_lint.py`: **`VERDICT: clean lint`** — 1086 calls scanned, all conform to §1.5; all 25 FKs have reverse-reachability.
- Cross-file audits (my own): 0 name collisions, 0 unresolved `grounds` refs, 0 unresolved stub back-references, 0 forbidden concurrency vocabulary, all 5 OCC endpoints declare their `expected_*_version` as required input and bump the parent version, no `id` used in any ordering/tie-break (all fall back to `created_at`).

### Reachability audit
BFS from each `initial_state` over declared transitions: **all 70 states across 16 axes reachable, 0 dead transitions**. Every error code is reached by a ladder rung or a named sibling in a rung's `note:`. Dead rules found **and fixed**:

1. **Rung 30 pre-empted sub-gate D entirely** — `ERR_PROGRAM_SESSION_MISMATCH` originally checked "the reservation's item satisfies the program's requirements", which fired before rungs 49/50/51 for *every* bad reservation, making `ERR_EQUIPMENT_FIT_MISMATCH` / `_INSPECTION_OVERDUE` / `_UNAVAILABLE` unreachable. Removed the equipment clause and dropped equipment-reservations from `applies_to`.
2. **`ERR_INSUFFICIENT_FUNDS` unreachable on an exhausted source** — rung 56 required `source.status == OPEN`, so an EXHAUSTED source always yielded `ERR_FUNDING_PERIOD_CLOSED`. Rescoped rung 56 to `status != CLOSED AND OperatingPeriod == OPEN`; aligned the ScholarshipAward precondition and the error's condition text.
3. **`ERR_AWARD_EXCEEDS_NEED` arithmetically infeasible** — both computed variants clamp to net need, so no legal input could cross it. Added the optional `requested_amount_cents` override that rungs 57/58 police.
4. **OCC field undefinable** — the funding-source *selector* made `expected_funding_source_version` unknowable to the client. Added `GET /recreation/funding-selection` (§1.5 ladder rung 2, a real operator surface) returning the selected source **and its version**; `funding_source_id` is now required on award create.
5. **Non-terminating cascade** — the CONFIRMED→WAITLISTED demotion frees a slot, which would re-trigger promotion. Pinned: promotion runs *only* in the withdraw transition, never for a slot freed by a demotion or by CASCADE B.
6. **Empty-roster floor** — `max(MIN_GROUP_STAFF, …)` made an empty session require 1 staffer, killing the empty-set boundary. Pinned an explicit `if pooled is empty: return 0` branch ahead of the floor.

### §1.8 / §1.9 instance counts
- §1.8: 22 instances — dual_variant 2, combinatorial 3 (modes a/b/c), non_linear_sm 2, transitive_cascade 2, priority_pair 3, boundary_precision 3, cross_entity 2, temporal_overlap 3, compensating_invariant 2.
- §1.9: 50 non-stub instances across entities / state_machines / calculations / validations / endpoints / errors / rbac / cross-cutting layers / consistency model, plus 11 stubs pointing at §1.8 instances by name.

### Other frictions & self-repairs
- **YAML lint caught the known `?` trap**: `input: [status?, limit?]` broke `safe_load` (bare `?` in flow context). Quoted every optional token across 29 endpoint rows.
- **Entity-budget squeeze**: merged the planned EquipmentModel + EquipmentUnit into a polymorphic `EquipmentItem` (`item_kind: SERIALIZED | POOLED`) to fit `OperatingPeriod` — the global-write-gate carrier — inside the 18–21 band. The merge is a net difficulty gain: the same `pooled_available >= 1` predicate now means exclusive occupancy for serialized rows and aggregate capacity for pooled rows, which is Rule 8's third interval semantics.
- **All formula-derived asserts were executed in Python before being written as literals** — series remainder (3858/3857 vs 4500), staffing ceilings (2 planned / 1 delivered; 250 pts → 1 under the pinned order vs 2 under the reversed one), the one-cent rounding-order gap (5322 vs 5321), zone-mileage fare (921 / 1171), and the partial-release ledger (8000/0/2000 summing to 10000).
- **Coverage gap to hand downstream**: the `EQUITY_WEIGHTED` waitlist variant and the `CONSECUTIVE` mastery variant are declared and reachable but no recipe asserts their divergence from `FIFO` / `N_OF_M`; the unit-test-generator should add those two from §1.3.

### Orchestrator independent verification
- `yaml.safe_load` all 3 files OK; top-level keys correct (SCAFFOLD.yaml carries neither design key).
- Counts re-derived from the parsed YAML: entities 21, endpoints 90 (**90 unique (method, path) pairs — 0 duplicates**), errors 70, calculations 19, state_machines 16, validations 60, invariants 5, roles 6.
- ALL_CAPS sweep: 141 tokens; 31 declared constants; 39 residual tokens after removing declared + enum + `ERR_*` — **all 39 manually confirmed to be enum members / mode names / status values** (e.g. `ZONE_MILEAGE`, `ROUND_PER_LINE`, `EQUITY_WEIGHTED`, `BAND_A..D`, `RESTRICTED_GRANT`), **0 undeclared numeric constants**.

## Step 4: Generate PRD — 2026-08-09T11:38:00.000Z

PRD written to `workspace/PRD.md`.

### Size
611 lines, 19,761 words, 141,869 bytes. Written in six bounded Write/Edit passes plus a generated-table pass; re-read end-to-end afterwards, no section dropped, no sentinel left behind.

### Outline
- **§1 Introduction** — 3 paragraphs (domain pain, allocation-plus-audit framing, the two governing commitments: *order is part of the contract* and *paired quantities are never interchangeable*).
- **§2 Global Specifications** — 12 subsections: 2.1 roles/headers/identity, 2.2 response envelope (verbatim), 2.3 pagination + list ordering + filter semantics, 2.4 logical clock & epoch checkpoint, 2.5 operating periods + global write gate + financial-write gate, 2.6 identifiers/timestamps/version, 2.7 path resolution & existence layer, 2.8 money/basis points/rounding, 2.9 OCC on parent rows, 2.10 the 60-rung ladder, 2.11 the 5 conservation invariants, 2.12 cascade discipline.
- **§3 Business Logic** — 9 subsections: 3.1 programme year (periods, cascade F, fee bands, programmes, sessions, cascade B), 3.2 intake (participants, cascade E, caregivers, assessments, consent, eligibility), 3.3 enrolment request + fee-band match + pricing + charge, 3.4 confirmation sub-gates/waitlist/cascade A/attendance, 3.5 staffing (certs, assignments, staffing math, lock/unlock/deliver, cascade C), 3.6 equipment (fit, holds, check-out/return fork, inspections, cascade D), 3.7 transport (runs, positions, fares), 3.8 funding (sources, selector, award sizing, encumber/disburse/release, sibling discount, family responsibility, payments), 3.9 goals/mastery/staffing debrief.
- **§4** 90-row endpoint table (4 columns). **§5** 70-row error table (2 columns).

### Self-audit (mechanically verified against the scaffold)
- **(a) 90/90 endpoints** — every `(method, path)` pair present as a table row; no duplicates.
- **(b) 70/70 error codes** — every id present with its exact HTTP status; each also mentioned in §2/§3 narrative.
- **(c) 60/60 rungs in order** — §2.10 enumerates 1…60 contiguously, marks the global write gate at rung 9 and the six sub-gate heads (34 A, 37 B, 45 C, 49 D, 52 E, 56 F), and states the exact rung subset the confirm/promotion walk visits (33, 34, 35, 37, 45, 46, 49, 50, 51, 54, 55, 60). Error precedence stated as "lower rung wins" with worked pairs.
- **(d) 10/10 dual-variant calcs, both branches** — session fee (PER_SESSION / SERIES_FLAT with floor-then-remainder-on-sequence-1), staff count (PLANNED / DELIVERED with the pinned double-ceil), cert validity (AT_ASSIGNMENT / AT_SESSION_DATE), effective tier (CURRENT / AS_OF_SESSION), fare (FLAT / ZONE_MILEAGE with a worked 1023/1273 example), family responsibility (ROUND_PER_LINE / ROUND_ON_TOTAL), award amount (NEED_PCT / FLAT_CAP), release (FULL / REMAINDER), waitlist score (FIFO / EQUITY_WEIGHTED), mastery (N_OF_M / CONSECUTIVE). The other 9 calcs are covered too.
- **(e) 16/16 status axes**, all transitions including every re-entry edge and both branches of each fork; all 6 cascades (A 8 hops, B 4, C 4, D 3, E 3, F 4) hop-by-hop, with the non-firing legs named (no promotion after cascade B or after a demotion; CHECKED_OUT reservations untouched by cascade D; DELIVERED sessions untouched by assessment activation; hop 4 of cascade C skipped at the unlock cap).
- **Contract 1**: 186 required identifiers (143 entity fields + endpoint inputs/outputs + 21 path params) — 0 missing. All 70 error ids, all 42 state values, all enum members, all 6 role names present in backticks.
- **Contract 3**: 1,293 backtick tokens in §3, 0 path tokens, 0 bare-method tokens, 0 method+path tokens.

### Places deliberately pinned where the scaffold was under-determined
1. **Sub-gate D during the confirm/promotion walk.** The scaffold's rungs 49–51 are written for reservation *creation*; applied literally to an already-held reservation, rung 51 (`pooled_available >= 1`) would always fail for a SERIALIZED item. Defined the walk to evaluate over the enrolment's live reservations: 49 and 50 quantify over that set (vacuously true when empty), and 51 requires the set to be non-empty → `ERR_EQUIPMENT_UNAVAILABLE`. All three stay reachable and the order is consistent.
2. **Sub-gate E during the walk.** Same problem. Defined as: skipped when `transport_requested` is false; satisfied when a live booking already exists; otherwise checks the session's runs for a free position matching the participant's `mobility_profile`.
3. **Sub-gate F during the walk** consists of rung 60 alone (56–58 guard award create/encumber only) — stated explicitly so the walk isn't read as demanding a funding source.
4. **Timestamp rendering** (scaffold silent): `created_at`/`updated_at` from real UTC with 3 fractional digits and *not* from the logical clock; caller-supplied instants echoed byte-for-byte; comparisons semantic, not string-wise. This is the recurring `.000Z` bug class, named head-on.
5. **Version bump granularity** (scaffold ambiguous): one bump per affected row per request, regardless of hop count.
6. **Off-enum filter values on GET lists** return an empty array rather than 400.
7. **`is_legal_guardian`** treated as required (no `?` in the scaffold input list), so its entity-level `false` default is not offered as an omission path.
8. **`scheduled_session_count`** is a pricing divisor only — the API does not refuse an extra session, since no error code exists for that.
9. **`enrollment_posture` on a plain participant read** is computed with no session nominated (consent branch skipped, check date = clock date).

### Orchestrator independent verification
- 611 lines / 19,761 words; 164 table rows; `grep -oE 'ERR_[A-Z_]+' | sort -u | wc -l` = **70** — matches the scaffold catalogue exactly.
- Section outline confirms §1–§5 with all 12 §2 subsections and all 9 §3 subsections present.

## Step 5: Generate unit tests — 2026-08-09T12:20:00.000Z

*(Steps 5 and 6 were launched concurrently in a single assistant message, `run_in_background: false` — parallel and blocking. Step 6 therefore had physical isolation from `test_suite/` for the first part of its run and was additionally forbidden from reading it.)*

Test infrastructure and suite generated and audited.

### Test counts

**95 `def test_` emitted** across 10 files under `test_suite/`, backed by 9 helper modules (1858 lines) under `test_helpers/`.

- **Queue A (Difficulty): 22 / 22 instances translated**, 44 tests — every instance has exactly 2.
- **Queue B (Corner): 50 / 50 non-stub instances translated**, 51 tests (`consent_rungs_reject_an_expired_artifact_and_an_unauthorised_signer` got 2 tests, one per limb).
- All 11 `excluded_because:` stubs verified: every `difficulty_instance` pointer resolves to a real §1.8 `name:`. No placeholder tests emitted for them.

### Skipped instances

**None.** Every non-stub instance in both indices passed the PRD-first two-condition filter and was translated.

One *assertion* inside a translated instance was dropped (the instance itself is still covered by 2 tests):

- `Difficulty/transitive_cascade/session_cancel_cascade_reaches_the_transport_run_counters` — the yaml asserts `TransportRun.status == CANCELLED` after the session cancel. §3.1's cascade B hop 4 says the cascade "moves a run that was `BOARDING_FULL` back to `PLANNED` as soon as either available counter rises above 0", while §3.7 says "A run is moved to `CANCELLED`, from either `PLANNED` or `BOARDING_FULL`, only by the session-cancellation cascade." Those two sentences give two PRD-faithful terminal states for the same row, so the run's post-cancel `status` fails unique derivability. The counter assertions (`accessible_committed` 0 / `accessible_available` 1, ambulatory pool untouched, `BOARDING_FULL` before the cancel) are unambiguous and are asserted.

### Near-miss register (thin PRD support, translated anyway)

1. `Corner/entities/participant_create_system_fields_input_ignored` — **closest call.** No PRD sentence says client-supplied system fields are *ignored*; support rests on the unconditional "The row is created in `status` `INTAKE` with `effective_support_tier` null and `version` 1" plus rung 22 (which polices only declared required fields' presence/type/range) and rung 23's closed enum list, neither of which licenses rejecting an extra field. A strict reader could 400 instead. Judged derivable because nothing in the ladder creates that rejection path.
2. `Corner/state_machines/participant_cycles_active_inactive_active` — the asserted final `version == 6` is a sum of three separate PRD claims (create → 1; "Creating a support assessment bumps the `Participant`"; activation bumps the participant; "Each move raises the participant's `version` by one"). Each link is verbatim, but the arithmetic is the test's own.
3. `Difficulty/boundary_precision_check/certification_expiring_exactly_on_the_session_date_is_still_valid` — asserting `qualified_at_session_date is False` on the *rejected* assignment. §3.5 says the flag "is stamped at creation and recomputed at assignment confirmation", and the value is already false at creation for that staffer, so the assertion holds under either reading of whether a failed confirm persists a recomputation.

### Setup made robust to a reading (assertions untouched)

- `session_cancel_cascade_reaches_the_transport_run_counters` — the yaml's `setup_api_calls` confirm the enrolment (with `transport_requested: true`) **before** any run exists. Per §3.7, "A session with no run at all and a participant who asked for transport therefore fails at whichever of the two rungs matches their mobility profile", so that confirm must fail with `ERR_ACCESSIBLE_POSITIONS_FULL` and the fixture would never build. Reordered to run → enrolment → booking → confirm, which satisfies sub-gate E under the "already holds a booking" clause on either reading of when the walk consults runs. Assertions unchanged.
- Timestamp handling: `assert_same_instant` parses both sides (`...Z` and `...mmmZ`) and is used for `rated_session_start_at`. The A06 yaml literal `2026-06-15T09:00:00.000Z` contradicts §2.6's byte-for-byte echo rule, so the test compares semantically against the session's own `start_at` rather than the yaml literal.

### Uncovered declared variants (reported, not invented)

The scaffold generator's suspicion is **confirmed** for both:

- **`EQUITY_WEIGHTED` waitlist scoring** — the string appears nowhere in either design index. No instance asserts its divergence from `FIFO`; the whole 25/50/100/0 + 50-for-award scoring formula in §3.4 is untested.
- **`CONSECUTIVE` mastery** — appears only once, as a `mastery_mode` payload value in `goal_rating_rungs_reject_unattended_sessions_and_duplicates`, whose assertions are `rating_count == 1` and two error ids. Its divergence from `N_OF_M` (the "newest rating is a miss" case) is never asserted.

No untagged tests were invented for either.

### Confirmations

- 0 `skip` / `skipif` / `xfail` / `pytest.skip` markers anywhere in `test_suite/` or `test_helpers/`.
- Every test carries exactly one `Design:` line, and it is the last line of the docstring.
- All 95 tags resolve to real instance names with the correct `rule_id` / `section` prefix.
- Every quoted PRD citation survives a whitespace-normalised literal match against `workspace/PRD.md`, and every quote is ≥8 words.
- `pytest --collect-only` collects 95 tests; pyflakes is clean on `test_suite/`.
- Entity-backed identities are threaded correctly: `make_activity_lead_headers(staff_id)` and `make_caregiver_headers(caregiver_id)` are used for every ownership-gated call; the shared-constant `ActivityLead` header exists solely for the deliberate `ERR_IDENTITY_NOT_FOUND` test. `FundingOfficer` headers are per-officer (`officer-1` / `officer-2`) so segregation-of-duties is genuinely exercised.

### Orchestrator independent verification
- `def test_` count across `test_suite/*.py` = **95**; `Design:` tag count = **95** — 1:1.
- `grep -rnE 'skip|xfail'` over `test_suite/` + `test_helpers/` → **1 hit, and it is prose inside a docstring** (`test_05:240` "Pooled items skip the inspection clause"), not a marker.

## Step 6: Generate implementation — 2026-08-09T12:20:00.000Z

Implementation complete and verified.

### Modules (4,785 lines total)

| Module | Lines | Role |
|---|---|---|
| `app.py` | 87 | stdlib-only entry point; socket-first `main()` |
| `application.py` | 55 | Flask factory, blueprint registration, error handler |
| `store.py` | 203 | in-memory tables, id/timestamp minting, logical clock, `touch()` |
| `errors.py` | 102 | 70-entry error catalogue + `ApiError` |
| `envelope.py` | 42 | `meta`/`response_type`/`data` envelope |
| `ctx.py` | 408 | ladder rungs 1–10 decorator, `Refs` (11–21), `Body` (22–23), pagination (24), OCC (25), `check_transition` (26/27) |
| `lookups.py` | 180 | cross-cutting row/child lookups, `current_period()` |
| `enums.py` | 52 | the 26 closed enum member sets + role sets |
| `calc.py` | 411 | the 19 calculations, all 10 dual variants |
| `engine.py` | 773 | counter recomputes, charge recompute, sub-gate walk, cascades A–F, epoch checkpoint |
| `serial.py` | 239 | per-entity response projection |
| `routes/` × 8 | 2,220 | 90 endpoints |
| `start.sh` / `requirements.txt` | 13 | guarded launcher |

### Route completeness gate

Diffed programmatically by **(method, path)** pairs: scaffold **90**, `app.url_map` **90**, **MISSING 0, EXTRA 0**.

### Timestamp three-case adjudication

PRD §2.6 verbatim: *"`created_at` and `updated_at` are minted from the server's own UTC clock — **not** from the logical clock — and are rendered as ISO 8601 UTC with exactly three fractional digits… Instants that the caller supplies … are stored and echoed back **byte-for-byte as the caller wrote them**; the server does not normalise, re-render or re-zone them… Where the server stamps a field from the logical clock … it writes the logical clock's current instant or date exactly as that clock currently holds it. A `GoalRating`'s `rated_session_start_at` is a verbatim copy of the rated session's `start_at` string."*

- **(a) server-written** — `created_at`/`updated_at` = `datetime.now(timezone.utc)` rendered `%Y-%m-%dT%H:%M:%S.mmmZ` (exactly 3 digits). Never the logical clock.
- **(b) caller-supplied echoed** — `start_at`, `end_at`, `effective_from`, `pickup_start_at`, `pickup_end_at`, `to_iso8601` are stored as the raw string and returned unchanged. All comparisons run on parsed instants, so `…T14:00:00Z` and `…T14:00:00.000Z` compare equal but read back differently. Verified: input `2026-06-01T14:00:00Z` reads back identically.
- **(c) derived from a caller-supplied instant** — `promoted_at` = `db.clock_raw`, the clock's *current string* verbatim (default `2026-05-01T00:00:00Z`); `current_utc` = the caller's `to_iso8601` unchanged; `signed_on` = the logical clock's calendar date `YYYY-MM-DD`; `inspection_due_date` after a PASS = clock date + 180 days; `rated_session_start_at` = byte-for-byte copy of the session's `start_at`. All four verified by assertion.

### Enum-error-routing closed rule

PRD rung 23 verbatim: *"The fields that route here are exactly the enum-typed inputs named in this document: `income_band`, `mobility_profile`, `guardianship_status`, `relationship`, `support_tier`, `consent_type`, `activity_type`, `risk_tier`, `pricing_mode`, `rounding_policy`, `waitlist_policy`, the members of `required_consent_types` and `required_certification_types`, `certification_type`, `assignment_role`, `item_kind`, `disposition`, `return_condition`, `position_type`, `fare_mode`, `source_kind`, `award_mode`, `mastery_mode`, `outcome`, `on_full` and `target_status`. **No other field routes here**; a malformed non-enum field is an `ERR_VALIDATION` (400) at rung 22 instead, and an out-of-enum *filter* on a read endpoint is not an error at all."*

Implemented exactly: those 26 names (and only those) are read through `Body.req_enum`/`opt_enum`/`opt_enum_list`, which defer membership to a second pass (`check_enums()`) run *after* every presence/type/range check — so a missing required field is always `ERR_VALIDATION` and a present-but-off-enum value is `ERR_INVALID_ENUM`. Every other field routes to `ERR_VALIDATION`. Read filters are never validated (an unknown filter value returns an empty page with `total_count` 0). Verified all three cases.

### Boot timing

`[boot] bound 0.0.0.0:<PORT> in 0.1 ms` on every launch (measured from process start to `listen()`). Achieved by keeping module scope stdlib-only and claiming the socket as the first act of `main()`, before importing Flask/blueprints. Retry loop: **280 attempts × 50 ms ≈ 14 s**, just inside the 15 s readiness budget. The bound fd is handed to `werkzeug.serving.make_server(..., fd=sock.fileno())`; werkzeug 3.1.8 constructs with `bind_and_activate=False`, so there is **no second bind**. `start.sh` guards `pip install` on `import flask`, reads `$PORT` (default 10000), binds `0.0.0.0`, and `exec`s in the foreground.

### Verification performed

Five hand-written smoke suites (~250 assertions) all pass, 0 failures, on fresh `start.sh` boots — covering all six cascades (A 8-hop incl. the promote→encumber→exhaust→lapse→unfunded→demote chain, B, C, D, E, F), all 10 dual-variant calculations (verified `ROUND_PER_LINE` 3704 vs `ROUND_ON_TOTAL` 3703 on identical inputs; `SERIES_FLAT` 3334/3333/3333; `ZONE_MILEAGE` 1023 vs `FLAT` 1000; NEED_PCT 2813 vs FLAT_CAP; FIFO vs EQUITY_WEIGHTED picking opposite winners; AT_ASSIGNMENT vs AT_SESSION_DATE disagreeing; CURRENT vs AS_OF_SESSION), non-monotone mastery (a rating on an *older* session evicting a hit → MASTERED→ACTIVE), rung precedence (9 beats 11 and 22; 4 beats 9; 22 beats 23; 26 vs 27), all five conservation invariants, and the once-per-request version bump (an 8-hop cascade raises the session's version by exactly 1).

### Reachability hypotheses (HYPOTHESES — verify by reading the code)

1. **Cascade B's `BOARDING_FULL → PLANNED` hop is unobservable.** §3.1 hop 4 restores counters and re-opens a full run, but §3.7 says *"A run is moved to `CANCELLED`, from either `PLANNED` or `BOARDING_FULL`, only by the session-cancellation cascade"* — so I also cancel every run serving the cancelled session in the same request. The hop runs; the visible end state is `CANCELLED`. Standalone `BOARDING_FULL→PLANNED` (booking cancel / no-show) is observable and tested.
2. **Rung 50 on the confirmation walk** is reachable only via (a) the epoch checkpoint's `SERVICEABLE→INSPECTION_DUE` sweep, which deliberately leaves `HELD` reservations alone, or (b) a still-`SERVICEABLE` serialized item whose `inspection_due_date` precedes the session date but not the clock date. The `OUT_OF_SERVICE` route is closed on that path because cascade D voids `HELD` reservations, and a `CHECKED_OUT` reservation cannot coexist with a `REQUESTED` enrolment.
3. **`ERR_INVALID_STATE` carries ~10 unnamed transition preconditions** (see A2 below). If any intends a different id, that error is *misrouted*, not unreachable.
4. **The epoch checkpoint does not blanket-recompute `qualified_at_session_date`** across all live assignments — only cascade C's lapsed ones. PRD authorises no version bump for untouched rows.
5. **Enrolment rows are not version-bumped** when `effective_support_tier_at_session` is re-derived by assessment activation or delivery; §3.2's activation clause enumerates exactly which rows gain a version (both assessments + the participant) and omits enrolments. The sessions whose counters were re-derived *are* bumped.
6. **`ERR_STAFFING_GAP` (rung 47) is reachable** despite sitting below 38/39/41: with zero assignments those rungs are vacuous over an empty set while a confirmed enrolment makes the gap non-zero.
7. **Rung 56 (`ERR_FUNDING_PERIOD_CLOSED`) is reachable** because it inspects the *source's own* operating period, which need not be the current period the gates at rungs 9/10 consult.

### PRD ambiguities resolved

- **A1** Runs of a cancelled session are themselves `CANCELLED` (§3.7's "only by the session-cancellation cascade"), though §3.1 hop 4 mentions only counter restoration.
- **A2** Transition preconditions the PRD states without an error id → `ERR_INVALID_STATE` (409) at rung 26: session open needs a future `start_at`; deliver needs clock ≥ `end_at`; attendance needs a locked, started session; assignment confirm/revalidate need an `OPEN`/`STAFFING_LOCKED` session; assignment withdraw from `CONFIRMED` needs a non-delivered session; certification-renewal date rules; enrolment withdrawal from `CONFIRMED` needs an `OPEN`/`STAFFING_LOCKED` session; booking confirm needs a `CONFIRMED` enrolment; participant→`ACTIVE` needs an active assessment.
- **A3** Signing a consent whose `expires_on` already precedes the clock date → `ERR_INVALID_STATE` (the scaffold lists it as a transition precondition beside the source-state check). The competing reading is `ERR_CONSENT_SIGNER_NOT_AUTHORIZED`.
- **A4** `GET /recreation/funding-selection` with a missing/unresolvable `enrollment_id` → `ERR_ENROLLMENT_NOT_FOUND` (404); rung 22 covers only POST/PATCH/PUT.
- **A5** Caregiver scope (rung 6) applies to endpoints naming a participant, enrolment, consent, goal, goal-rating, enrolment-charge **and caregiver** (a caregiver row names a participant via `participant_id`, per §2.1's "every resource that names a participant"). It fires only on ids that *resolve*; unresolvable ids fall through to the 404 rungs. List endpoints check explicit id filters only — results are never silently filtered, because no PRD sentence authorises filtering.
- **A6** A charge's `program_fee_cents` is pinned at creation, not refreshed on recompute (§3.8 enumerates the refreshed fields and omits it). Since the band is pinned, both readings produce the same number.
- **A7** Attendance refreshes the session's slot counters — §2.11 lists "attendance" among the events after which `slots_committed == count(CONFIRMED)` must hold — which bumps the session's version even though §3.4 names only the enrolment.
- **A8** A `PASS` inspection pushes `inspection_due_date` to clock+180 unconditionally, including on `POOLED` rows (the §3.6 PASS sentence is unqualified), despite pooled items having no inspection cycle.
- **A9** `expected_funding_source_version` is required on award creation even when `funding_source_id` is omitted; it is then compared against the selector's winner, which is exactly the number §2.9's funding-selection read hands back.
- **A10** `dedicated_participant_id` on a non-`ONE_TO_ONE` assignment is stored as null rather than rejected ("null otherwise" read as the stored value, not a prohibition); its existence is still validated at rung 11 whenever present.
- **A11** On cascade-A withdrawal, `funding_status` becomes `RELEASED` only when at least one award was actually released; an award-less enrolment keeps `QUOTED`.

### Orchestrator independent verification
- 20 `.py` modules under `workspace/implementation/`.
- `grep -rnE 'sqlite|json\.dump|pickle|/tmp|open\('` over `implementation/*.py` → **empty**. In-memory only, no seeding path.

## Step 7: Run tests and iterate — 2026-08-09T13:15:00.000Z

Done — clean 8-round sweep.

**Iterations run: 2**
- Iteration 1: 2 failing tests (identical in all 8 rounds — deterministic, not flaky).
- Iteration 2: 0 failing tests, all 8 rounds.

**Tests deleted:** none. Both failures were STEP 2 (test-vs-PRD consistency) issues, not PRD-silence.

**Fixes applied to `test_suite/`** — all in `test_suite/test_03_enrollment_and_confirmation.py`:

Both failures shared one root cause: the setup helper `_delivered_session_leaving_an_outstanding_charge()` delivered session A (leaving an `OUTSTANDING` charge) and only *then* had the tests call `request_enrollment(participant, session_b)`. PRD §3.2 puts rung 60 on enrolment **creation** as well as confirmation, verbatim:

> "Finally, at the bottom of the ladder, the family balance rung applies here as well: a participant carrying an `OUTSTANDING` charge on an already-delivered session cannot request a new place, and is refused with `ERR_FAMILY_BALANCE_OUTSTANDING` (402)."

(and §2.10 rung 60 names creation explicitly). So the implementation's `HTTP 402` at the setup step was **PRD-correct**; the fixture was constructing a precondition the PRD forbids, and the tests never reached the confirmation ladder they were about. The design instance (`Difficulty/priority_pair_validation_conflict/state_rung_28_beats_fiscal_rung_60_on_confirm`) is only expressible if the place on session B is taken while the family balance is still clean.

- Refactored the setup into three helpers: `_staffed_session_a()` (phase 1), `_attend_and_deliver()` (phase 2), and a new `_outstanding_balance_and_a_locked_second_session()` that interleaves them — session B is created, opened and **requested before** session A is delivered, then session A is attended+delivered, then session B is locked so rung 28 and rung 60 are both genuinely violated at the confirm call. `_delivered_session_leaving_an_outstanding_charge()` was preserved (rebuilt on the same phases) because the already-passing `test_outstanding_balance_on_a_delivered_session_blocks_a_new_enrollment` depends on it.
- `test_session_not_open_pre_empts_the_outstanding_family_balance_on_confirm` and `test_the_locked_session_refusal_names_the_state_rung_not_the_fiscal_rung` now call the new helper. **No assertion was changed** — both still demand the exact `ERR_SESSION_NOT_OPEN` / 409, and the second still asserts `error_id != ERR_FAMILY_BALANCE_OUTSTANDING` and that session A is `DELIVERED` with an `OUTSTANDING` charge. The change made the tests strictly more faithful to PRD.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** **none.** Consequently there is no new reachable state and no PRD prose falsified by this iteration — the implementation is byte-identical to what Step 6 produced.

**PRD frictions noted for Step 8 (no action needed):**
1. **The handed-down one — post-cancel `TransportRun.status`.** §3.1 hop 4 describes cascade B moving a run "that was `BOARDING_FULL` back to `PLANNED`", while §3.7 says a run reaches `CANCELLED` "from either `PLANNED` or `BOARDING_FULL`, only by the session-cancellation cascade". The two sentences give the same cascade two different end states for the same run. Step 5 correctly dropped that single assertion; the impl resolves it by fiat (A1) as `CANCELLED`. Genuinely under-determined — flagging as required.
2. **Rung 60's scope is stated twice with different reach.** §2.10 rung 60 lists "enrolment creation, enrolment confirmation and the promotion walk"; §3.2's prose renders the creation case only, as the last of "five business questions". A reader working from §3.2's numbered walk alone could miss that the same rung also sits on confirm and on the promotion walk. This is the exact seam both failing tests sat on, and it is worth pinning — the §2.10 statement is the complete one.
3. **Rung 28 vs rung 60 precedence is only derivable from the global rule.** Neither rung's own sentence mentions the other; the tests lean entirely on §2.10's "the lower rung number wins, and it resolves every ambiguity in this document". That global sentence does the work, but it means the confirm ladder's ordering is nowhere stated locally.

**Final sweep evidence:** rounds 1–8 each `rows=95 passed=95 failed=0`; name-sets across all 8 rounds are **identical**. Sweep run at wave size 3 (2 foreign runners co-tenant), ~3.3 min wall clock.

### Orchestrator independent verification
- All 8 `results.N.json` parsed: **95 rows each**, `uniq=95`, status set exactly `{'passed'}`, sorted-name **sha256 `13c18af859ed` identical across all 8 rounds**.
- `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.1.json` → **empty** (nothing edited after the winning sweep started).
- `def test_` count still **95**.
- **Route completeness re-diffed by the orchestrator by (method, path)**, normalising both `{param}` and `<param>` forms: scaffold **90**, `app.url_map` **90**, **MISSING 0, EXTRA 0**. (A first pass with a `<...>`-only normaliser printed 53 mirrored MISSING/EXTRA rows — a normaliser artefact, not a route gap; re-run with the corrected regex is clean.)

## Step 8: Finalize PRD — 2026-08-09T13:22:00.000Z

`PRD_FINALIZED.md` is written.

### Size

| | PRD.md | PRD_FINALIZED.md |
|---|---|---|
| lines | 611 | 611 (0.0% delta — all edits are in-paragraph) |
| bytes | 141,869 | 144,493 (**+1.85%**) |

5 paragraphs touched, no sections added, no prose deleted.

### Changes

- **§3.1 (cascade B, hop 4)** — *revise* — after the counter restoration, pinned that **every** run serving the cancelled session whose `status` is `PLANNED` or `BOARDING_FULL` is moved to `CANCELLED` in the same request (including runs with no affected booking and runs with no booking at all), so the `BOARDING_FULL → PLANNED` restoration is never observable, and every such run's counters are recomputed and `version` raised — `engine.py:512-518` (`cancel_session`), `engine.py:67-93`.
- **§3.7 (run oscillation paragraph)** — *revise* — same subject, second site: named the session-cancellation cascade as the single exception to "the run moves back to `PLANNED`"; the pre-existing "`CANCELLED` … only by the session-cancellation cascade" sentence is kept verbatim — `engine.py:514-518`, `routes/transport.py` (no client-driven run cancel exists).
- **§3.3 (five business questions, family-balance sentence)** — *insert* — recorded that rung 60 sits at three places, not one: creation (402), confirmation (402), and the promotion walk (silent skip, not a refusal) — `routes/enrollments.py:134`, `engine.py:375`, `engine.py:388-392`.
- **§3.4 (sub-gate walk paragraph)** — *insert* — stated the confirm ladder's local ordering: rungs 26/27 (enrolment still `REQUESTED`; named the four terminal statuses) then rung 28 (session still `OPEN`) are settled before any sub-gate, so `ERR_SESSION_NOT_OPEN` pre-empts rung 60; and `on_full` does not soften it (routing is rungs 45/46 only) — `routes/enrollments.py:208-215`, `ctx.py:397-408`, `engine.py:326-337`.
- **§3.4 (Promotion paragraph)** — *insert* — sibling pin: the promotion walk is preceded by the participant-active rung 33 as at confirmation, and rung 28 is deliberately *not* in that walk (which is what lets a promotion run on a `STAFFING_LOCKED` session) — `engine.py:300-306`, `engine.py:388-392`, `engine.py:480-484`.

### Per-edit pre-edit search log

1. **§3.1 hop 4** — (a) subject: post-cascade `TransportRun.status`. (b) enumerated every impl write to `run["status"]`: `engine.refresh_run_status` (`engine.py:84-97`) and its four callsites — booking create (`routes/transport.py:161`), `cancel_booking` (`engine.py:433-438`), attendance no-show (`routes/enrollments.py:271-274`), `deliver_session` no-show sweep (`engine.py:667-670`) — plus the only direct `CANCELLED` write (`engine.py:516-517`); grepped `routes/transport.py` for a client-driven run transition (none exists); read `lookups.runs_of_session` (`lookups.py:115`) and `refresh_run_counters` (`engine.py:67-80`, `bump=True`). (c) wording widened from "each affected run" to "**every** transport run serving the cancelled session … booked or not", because the impl loops `runs_of_session` unconditionally, and the version claim was made explicit for booking-free runs since `refresh_run_counters` touches them.
2. **§3.7 oscillation paragraph** — (a) subject: same as (1), the `BOARDING_FULL → PLANNED` restoration claim. (b) re-checked the three non-cascade-B freeing paths (booking cancel, attendance no-show, deliver no-show) confirm the run stays `PLANNED`. (c) scoped the exception to the session-cancellation cascade only, so withdrawal/exit/no-show paths keep the unchanged `PLANNED` outcome.
3. **§3.3 rung 60** — (a) subject: scope of the family-balance rung. (b) grepped `calc.financial_gate_blocked` — exactly three consumers: `routes/enrollments.py:134` (creation, raises 402), `engine.py:375` inside `_walk_sub_gates` (reached by both `confirm_gate`, which raises 402, and `promotion_gate_ok`, which converts to a silent skip), and `calc.py:395` (eligibility posture / `financial_gate_ok`, a read). Read `calc.financial_gate_blocked` (`calc.py:350-360`) to confirm the predicate is per-participant, not per-household. (c) split the outcome per site — "raises 402" at confirm vs "silently skipped" at promotion — instead of a single "refused", which would have mis-described `promotion_gate_ok`.
4. **§3.4 rung-28 precedence** — (a) subject: what is evaluated before the sub-gate walk at confirmation. (b) read `confirm_enrollment` (`routes/enrollments.py:201-228`), `ctx.check_transition` (`ctx.py:397-408`), `ENROLLMENT_TERMINALS` (`routes/enrollments.py:27`), and the `on_full` routing sites (`engine.py:326-337`) to confirm routing touches only rungs 45/46. (c) avoided claiming rung 28 is *first* — rungs 26/27 precede it — and enumerated the exact terminal set rather than saying "a terminal row".
5. **§3.4 promotion** — (a) subject: which rungs the promotion walk performs. (b) read `_walk_sub_gates` (`engine.py:296-380`) confirming rung 33 is inside it and no session-status check is; confirmed `_walk_sub_gates` has exactly two callers; confirmed `run_one_promotion` is invoked only from `withdraw_enrollment` (`engine.py:480-484`), whose session may be `OPEN` or `STAFFING_LOCKED` (`routes/enrollments.py:240-243`). (c) stated rung 28's absence as a negative only after verifying no session-status branch exists anywhere in the walk.

### Sibling-derivation sweep

- **Shape "one cascade, two stated end states for the same row"** — swept every cascade-B mention in the PRD (lines 230, 231, 233, 238, 242, 262, 389, 391). The run-status pair (§3.1 hop 4 vs §3.7) was the only divergent one; both sites are now pinned. §3.7's booking-lifecycle sentence (line 389) was checked against `engine.cancel_session` — the charge recompute happens via the `touched_enrollments` loop — and left verbatim. The conservation-invariant bullets make no run-status claim and were left verbatim.
- **Shape "a rung whose §2.10 scope is broader than its §3 rendering"** — swept the confirmation/promotion rung family (28, 33, 45, 46, 49–51, 54, 55, 60). Sub-gates A–F are already covered at promotion by "all six sub-gates"; rungs 54/55 are covered by §3.7's closing paragraph; rung 50's check-out reach is covered in §3.6. The only genuine siblings were **rung 60 at confirm/promotion** (edit 3) and **rung 33 at promotion** — the one walked rung that is not a sub-gate and so falls outside "all six sub-gates" (edit 5). **Rung 28 was explicitly ruled out at promotion**: the impl does not check it there, so its *absence* was pinned rather than widening it.

### New state reachable / prose falsified

1. **Post-cancel run status** — makes reachable a `TransportRun` in `CANCELLED` that never held a booking (previously the PRD only described runs whose counters moved). That falsified §3.1's implicit "affected run" scoping and falsified the plain reading of §3.7's "the run moves back to `PLANNED`" under cascade B; both now pinned.
2. **Rung 60 at confirm/promotion** — makes reachable an `ERR_FAMILY_BALANCE_OUTSTANDING` (402) *on the confirm endpoint*, and a silently skipped promotion candidate with a clean gate record otherwise. That falsified §3.3's framing of the rung as a request-time-only question. (This is the seam both Step 7 failures sat on; the impl needed no change.)
3. **Rung 28 before rung 60 on confirm** — makes reachable an `ERR_SESSION_NOT_OPEN` on a confirm whose participant *also* fails rung 60, i.e. a 409 where a reader of §3.4 alone might expect the 402. Falsified nothing in the existing prose (§2.10's global lower-rung-wins rule already implied it) — the edit converts a globally-derivable fact into a locally-stated one.

### Orchestrator independent verification
- 611 → 611 lines, 141,869 → 144,493 bytes (+2,624).
- `diff` of the heading lists → **identical**; table-row count 164 → 164. No section added or dropped.

## Step 9: Complete PRD — 2026-08-09T13:38:00.000Z

`PRD_COMPLETED.md` is complete. Structure verified: all headings preserved, §4 endpoint table still 90 rows, §5 error table still 70 rows.

### Scale

| | value |
|---|---|
| PRD_FINALIZED.md | 611 lines / 144,493 chars |
| PRD_COMPLETED.md | 615 lines / 162,644 chars |
| char delta | **+18,151** |
| edits | **41** (37 ambiguity-pins, 4 mismatch-revisions) |

### Per-question yield

| Q | edits |
|---|---|
| Q9 preconditions not numbered as rungs | 8 (rung-26 cluster of 12 + 7 workflow-side error-id/order pins) |
| Q1 reporting-only figures | 4 |
| Q2 response projections | 1 |
| Q3 list ordering / filters / pagination | 4 |
| Q4 defaults & null-vs-omitted | 3 |
| Q5 timestamp rendering | 1 |
| Q6 cascade legs that do not fire | 6 |
| Q7 version-bump ledger | 5 |
| Q8 error precedence / 404 routing | 5 |
| Q10 dual-variant branches | 3 |
| R1 conservation invariants | 0 (all derivable as written) |
| R2 OCC | 1 |

### Verdicts on inherited claims

- **Epoch-checkpoint recompute scope — CONFIRMED, and the PRD was wrong.** §3.5 asserted `qualified_at_session_date` is "recomputed … by the epoch checkpoint". The checkpoint only sets it `false` on assignments its cascade lapses. **Mismatch revised.**
- **Enrolment rows not bumped when `effective_support_tier_at_session` is re-derived — CONFIRMED** (`engine.py:646`, `engine.py:677`: assignment without `touch`). Pinned in §2.6 and §3.2.
- **Rung 50 on the confirmation walk — REFINED.** Reachable via the epoch checkpoint pushing a `SERIALIZED` item with a live `HELD` reservation to `INSPECTION_DUE`, and via a `CHECKED_OUT` reservation surviving a FAIL/RETIRE on an enrolment later demoted to `WAITLISTED`. Not a PRD statement, so no edit.
- **Rungs 47 and 56 — CONFIRMED reachable.** Rung 47 additionally pinned as reading a *non-persisted* recompute.
- **A3 expired-consent → `ERR_INVALID_STATE` — CONFIRMED**, and pinned as rung 26, pre-empting rung 36.
- **A4 funding-selection 404 — CONFIRMED**: a missing/empty/unresolvable `enrollment_id` query param is `ERR_ENROLLMENT_NOT_FOUND`, pre-empting `ERR_INSUFFICIENT_FUNDS`.
- **A5 caregiver scope — CONFIRMED and materially under-specified.** Scope is a *rejection* mechanism only; a `CaregiverUser` who omits the filter on any scoped list gets the full unfiltered page. Also skipped entirely when the named row doesn't exist (falls through to 404).
- **A6 `program_fee_cents` pinned at creation — CONFIRMED**, already adequately pinned.
- **A7 attendance bumps the session — CONFIRMED**; pinned (`refresh_session_counters` on both outcomes).
- **A8 PASS pushes `inspection_due_date` on POOLED rows — CONFIRMED**; a pooled row can end up with a non-null date. Pinned along with the contradiction resolution.
- **A9 `expected_funding_source_version` always required — CONFIRMED, and REFINED**: when no source is named *and* the selector is empty, rung 25 is skipped altogether, so `ERR_INSUFFICIENT_FUNDS` is reported, never `ERR_STALE_VERSION`.
- **A10 `dedicated_participant_id` — REFUTED as "stored".** It is still resolved at rung 11 (so a bad id 404s even on a `GROUP` role) but then **discarded**; the row is written with null.
- **A11 `funding_status` → `RELEASED` — CONFIRMED and the PRD was wrong.** §3.4 stated it unconditionally in cascade A hop 2; it fires only if at least one award was actually released. Also refined on the quiet (`REQUESTED`/`WAITLISTED`) path, where it only follows an axis already at `ENCUMBERED`.

### Highest-value new findings (no test could see these)

- **Cascade B does not release equipment reservations or scholarship awards** — an entire absent leg the PRD never mentioned.
- **Delivery has a fifth, unstated hop**: it re-derives *every* enrolment's `effective_support_tier_at_session` under `AS_OF_SESSION` **before** computing `required_group_staff_delivered`, so the delivered requirement reads the rewritten tiers.
- **Promotion ranks on a freshly recomputed score, not the stored `waitlist_score`** — the two can disagree. Same shape for rung 47 vs. stored `staffing_gap`.
- **Rungs 57 before 58**: §3.8 described the award-sizing checks in the opposite order to the ladder.
- **Sibling discount counts self only while this enrolment is itself `CONFIRMED`.**
- **`EQUITY_WEIGHTED`**: null tier → 0 points; bonus added at most once; unresolvable programme → 0. **`CONSECUTIVE`**: `mastery_window_m` is entirely inert.
- A null effective tier counts as *pooled*, so the one-staffer floor applies to an all-null roster (requirement 1, not 0).
- Goal ratings may be recorded against a `DISCONTINUED` goal; rating creation picks the **earliest** enrolment by `created_at` when several exist on the same session.
- Family payments have no lower bound on `amount_cents` and no charge-status precondition.

### Orchestrator independent verification
- 611 → 615 lines; 144,493 → 162,644 chars (+18,151).
- `diff` of heading lists PRD_FINALIZED → PRD_COMPLETED → **identical**; distinct `ERR_*` ids still **70**.
- `find test_suite test_helpers workspace/implementation -name '*.py' -newer results.1.json` → **0** — Step 9 touched no code, so the 8×95/95 sweep evidence still describes the shipped implementation.

## PIPELINE COMPLETE — 2026-08-09T13:40:00.000Z

**95/95 tests passing on all 8 sweep rounds.** 0 test deletions, 0 `test_helpers/` fixes, 2 `test_suite/` setup-helper fixes (1 shared root cause), **0 `implementation/` fixes**. Step 8 made 5 edits; Step 9 made 41.






