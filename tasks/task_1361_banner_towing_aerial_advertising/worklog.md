# Worklog — task_1361_banner_towing_aerial_advertising

## Step 1: Create Task Directory — 2026-08-13T00:00:00.000Z

Task directory `tasks/task_1361_banner_towing_aerial_advertising/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE. No index scan performed, no other task directory touched.

User difficulty directive: "Generate task hard than expert level!" — conveyed to the scaffold generator as a difficulty target (push §1.8/§1.9 depth/breadth beyond the standard expert tier); scenario text itself passed verbatim.

## Step 2: Generate Scaffold — 2026-08-13T01:05:00.000Z

All three files are present, valid YAML, and lint-clean. Final summary (verbatim from subagent):

Scaffold artifacts written for `task_1361_banner_towing_aerial_advertising`:

- `SCAFFOLD.yaml`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `SCAFFOLD_CORNER_DESIGN.yaml`

### Counts

- **Entities**: 17 (Base, Aircraft, Pilot, Route, Client, Campaign, AirspaceApproval, TFRRestriction, Banner, BannerRevision, SeasonalCapacity, FlightSlot, WeatherAssessment, FlightLog, MakeGoodCredit, ProofOfFlight, Invoice)
- **State machines**: 10 (Campaign, Banner, BannerRevision, AirspaceApproval, FlightSlot, MakeGoodCredit, Pilot, Aircraft, Invoice, TFRRestriction)
- **Calculations**: 10 (go_no_go_decision, flight_hour_billing, weather_cancellation_penalty_rule, make_good_credit_application, aircraft_selector, pilot_selector, banner_revision_refab_trigger, seasonal_capacity_consumption, pickup_failure_suspension_threshold, tfr_overlap_detection)
- **Validations**: 23 (across auth/existence/state/business_safety/business_constraint/business_temporal/business_fiscal/business_referential)
- **Endpoints**: 79 (includes `/_clock/set_current_utc`, full CRUD + action endpoints + 6 reverse-reachability filtered lists)
- **Error codes**: 30
- **Roles**: 7 (PlatformAdmin, Client, Dispatcher, Pilot, GroundCrewLead, ComplianceOfficer, FinanceOfficer) — `role_model: segregation_of_duties`
- **OCC concurrency rules**: 3 (campaign-book, flight-slot-book vs SeasonalCapacity, banner-fabricate)
- **§1.8 instances**: 18 (9 rules × 2 instances, all with concrete setup_api_calls and literal asserts)
- **§1.9 instances**: 24 (across entities / state_machines / calculations / validations / endpoints / errors / rbac / cross-cutting layers)

### Notable design decisions

- **Primary archetype**: quota/allocation (SeasonalCapacity pool consumed by FlightSlot booking) blended with **ledger reconciliation** (invoice assembly with waterfall credit application + penalty rounding rules).
- **FlightSlot** is the dense coupling hub — it depends on Banner, AirspaceApproval, Route, Aircraft, Pilot, SeasonalCapacity, and TFRRestriction. Five cross-entity gates on a single DRAFT→BOOKED transition.
- **BannerRevision → Banner** forms a true cycle: any new ACTIVE revision forces banner back to DRAFT, requiring refabrication.
- **Pilot suspension cascade**: 3rd FAILED pickup auto-suspends pilot and reverts their SCHEDULED slots to BOOKED with `assigned_pilot_id` cleared.
- **MakeGoodCredit waterfall** pinned to (expires_on_local ASC, created_at ASC) with per-credit status transitions OPEN → PARTIALLY_APPLIED → FULLY_APPLIED.
- **Tiered pricing on flight_hour_billing**: per-line round_half_up, then sum, then discount factor — explicitly pinned rounding order to prevent off-by-cents drift.
- **Half-open interval semantics** pinned for both aircraft double-booking and TFR overlap detection (adjacent windows allowed).
- **Segregation of duties**: ComplianceOfficer who grants an approval cannot file FlightLogs on slots using it (validation priority 22).
- **Logical clock** with startup default `2026-08-01T00:00:00Z` enables deterministic weather/notice/TFR tests.

`scaffold_lint.py` reports **VERDICT: clean lint** — all 549 §1.8/§1.9 calls conform to §1.5, and all §1.1 FKs have reverse-reachability GETs.

(Orchestrator note: the subagent's first turn ended before writing files; it was resumed via SendMessage and completed all three files including filling 5 placeholder instances and 3 lint-fix iterations. File sizes: SCAFFOLD.yaml 1952 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1777 lines, SCAFFOLD_CORNER_DESIGN.yaml 1131 lines.)

## Step 3: Copy Shared Files — 2026-08-13T01:05:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1361_banner_towing_aerial_advertising/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T01:18:00.000Z

PRD generated and verified. Summary (verbatim from subagent):

**Output:** `workspace/PRD.md` — 308 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 RBAC (7 roles with entity-backed vs opaque identity prose), 2.2 API Response Structure (byte-identical verbatim block, confirmed programmatically), 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning (incl. immutable WeatherAssessment/ProofOfFlight exception), 2.5 The Logical Clock (default `2026-08-01T00:00:00Z`), 2.6 Nested Resource Retrieval, 2.7 Validation Pipeline fixed order, 2.8 Seasonal Capacity Accounting, 2.9 Money/Hours/Precision, 2.10 OCC (all 3 rules), 2.11 Hierarchical Consistency & Cascades
- §3 Business Logic (8 subsections): 3.1 Bases/Fleet/Routes/Quotas, 3.2 Clients & Campaigns, 3.3 Banners & Revisions, 3.4 Airspace Approvals & TFR, 3.5 Flight-Slot Booking & Selectors, 3.6 Flight-Day Ops (schedule/weather/flight log), 3.7 Proof of Flight, 3.8 Billing/Credits/Settlement
- §4 Endpoint Definitions (all 79 scaffold endpoints, 4-column table)
- §5 Error Code Catalogue (all 30 errors, 2-column table)

**Scaffold rule coverage (Contract 2 — all expressed as prose):**
- State machines: 10/10 machines, 42/42 transitions (from/to states, actors, preconditions paired with error IDs, side effects including all cascades)
- Calculations: 10/10 (go/no-go thresholds, tiered billing with pinned rounding order + provisional/final variants, 72h/24h penalty boundaries with inclusivity, credit waterfall ordering, both selector scoring formulas with 600/500-hour caps, pinned refab propagation order, capacity aggregation, suspension-at-3 threshold, half-open TFR overlap)
- Validations: 23/23, with explicit priority ordering (global pipeline in §2.7; per-endpoint orderings for slot booking and flight-log filing in §3.5/§3.6)
- Concurrency rules: 3/3 (endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 each named)
- Errors: 30/30 mentioned in §2/§3 prose; roles 7/7; all 35 state values and all enum values present as exact backticked strings

**Zero-Silence / Hard Contract compliance:**
- Contract 1 (field names): 98 required identifiers (entity fields + endpoint inputs + named outputs like `current_utc`, `expired_credit_count`, `cancelled_at_utc`), 98 present in backticks, 0 missing
- Contract 2 (rules): PASS per above — every rule-bearing scaffold entry appears as explicit prose
- Contract 3 (§3 path purity): 441 backticked tokens scanned in §3, 0 violations (no URL paths, no bare HTTP methods)

Note on process: the first two verification runs reported false "all missing" results because the heredoc-mangled regex matched across multi-backtick spans; after fixing the tokenization, the real gaps surfaced (5 tokens) and were repaired, with the final diff empty.

## Step 5: Generate Unit Tests — 2026-08-13T01:55:00.000Z

Generation complete. Final summary (verbatim from subagent):

## Test counts per queue
- **Queue A (Difficulty): 36 tests** — all 18 non-stub instances from §1.8 covered with exactly 2 tests each.
- **Queue B (Corner): 24 tests** — 23 of 24 non-stub instances from §1.9 covered (run_ops instance got 2 tests); **1 instance skipped**.

## Skipped instance (1)
- **`Corner/state_machines/cancelled_campaign_is_terminal`** — *asserted outcome contradicts the PRD*. The instance asserts `ERR_ALREADY_TERMINAL` on cancelling a CANCELLED campaign, but PRD §2.7 pins the opposite precedence verbatim: the from-state check "runs before the terminal-state lockdown ... so a request against a terminal resource whose transition would also be invalid surfaces the from-state error first." The PRD uniquely derives `ERR_INVALID_STATE`, so the instance as written fails the two-condition filter. Gap left as a gap (no placeholder, no skip marker).

## Corrections made to design-index recipes (PRD-first adjudication)
- **`Difficulty/dual_variant_calc/flight_billing_provisional_vs_final`** — recipe's S2 (15:00Z, 3h) overlaps S1 (14:00Z, 2h) on the single aircraft and would fail booking with `ERR_AIRCRAFT_DOUBLE_BOOKED` under any PRD reading. Moved S2 to 16:00Z, 2h (adjacent, no overlap); expected preview subtotal recomputed from PRD-forced values: 1.5×30000 + 2×30000 = **105000** (recipe's 135000 was unreachable). Second test for the instance uses a FLOWN + CANCELLED_CLIENT scenario proving the preview excludes penalties.
- **`Difficulty/boundary_precision_check/visibility_exactly_3_sm_is_go`** — the instance asserts `GO`, but PRD §3.6 ("visibility below 5.0 statute miles ... yields `MARGINAL`") uniquely derives **MARGINAL** at exactly 3.0 SM (not NO_GO, since 3.0 is not below 3.0). Emitted with the PRD-correct expectation plus the 2.9 SM → NO_GO → WEATHER_HOLD counterpart boundary test.
- **`Corner/errors/error_unauthorized_when_role_mismatch`** — recipe had an empty setup, but a Pilot role with a non-persisted X-User-ID must yield `ERR_UNAUTHENTICATED` (PRD §2.1 identity check), never 403. Setup now registers a real pilot so the request survives authentication and fails at the role-permission stage.

## Files generated
- **test_helpers/** (9 files): `__init__.py` (barrel: framework + PRD-specific), `types.py` (17 entity TypedDicts; `WeatherAssessment`/`ProofOfFlight` correctly carry only id + created_at per PRD §2.4), `api_client.py` (all 55 PRD endpoints), `api_errors.py` (31 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (7 roles; `make_client_headers`/`make_pilot_headers` builders for the two entity-backed roles, used for every ownership-gated call), `fixtures.py` (composite tiers: `setup_operation` workhorse, `create_ready_banner`, `book_slot` with fresh OCC reads, `weather_cancel_slot`, `fly_slot`, `issue_invoice`).
- **test_suite/** (10 files): `conftest.py` + `test_01_security_and_ownership.py` (4), `test_02_base_fleet_setup.py` (5), `test_03_campaign_lifecycle.py` (7), `test_04_banner_fabrication.py` (6), `test_05_slot_booking_and_airspace.py` (11), `test_06_scheduling_and_weather.py` (7), `test_07_flight_logs_and_pilot_suspension.py` (6), `test_08_capacity_credits_ops.py` (6), `test_09_billing.py` (8).

## Verification
- All 60 tests collect cleanly under pytest; pyflakes clean; zero `skip`/`skipif`/`xfail` markers; zero scaffold references in comments/docstrings.
- **Every emitted test carries exactly one `Design:` tag** (60/60), all resolving to real instance names in the source yamls; all 18 difficulty instances have ≥2 tests, all covered corner instances have ≥1.
- Final PRD-citation pass: every ≥8-word quoted docstring fragment survives a literal grep of `workspace/PRD.md` (0 verbatim failures).

## Step 6: Generate Implementation — 2026-08-13T02:05:00.000Z

Implementation complete and verified. Summary (verbatim from subagent):

## Files (all under `workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Guarded install (`import flask` check), `exec python3 app.py`, foreground |
| `requirements.txt` | 1 | `flask>=3.0,<4` |
| `app.py` | 38 | Flask entry, `0.0.0.0:$PORT` (default 10000), envelope-wrapped 404/405/500 handlers |
| `db.py` | 66 | In-memory `DB` dicts (empty at boot), logical clock pinned at `2026-08-01T00:00:00Z`, UUID minting, 3-fractional-digit ISO timestamps |
| `errors.py` | 9 | `ApiError(error_id, http_status, message)` |
| `response.py` | 40 | PRD §2.2 envelope (`meta`/`response_type`/`data`, pagination fields in `meta`) |
| `middleware.py` | 67 | X-User-Role/X-User-ID auth (401/403), entity-backed identity for Client/Pilot, owner guards |
| `util.py` | 214 | Typed field validators (`ERR_INVALID_REQUEST`/`ERR_INVALID_ENUM`), ISO/date/month parsing, half-up Decimal rounding, limit/offset pagination (10/0, 1–100) |
| `services.py` | 581 | Counters, cascades, capacity accounting, selectors, go/no-go, billing waterfall |
| `routes/ops.py` | 407 | Clock, bases, aircraft, pilots, routes, seasonal capacities, run_ops |
| `routes/clients.py` | 242 | Clients, credit hold, campaigns, book/cancel, billing_preview |
| `routes/banners.py` | 328 | Banners + revisions (propose/approve/reject, refab trigger) |
| `routes/compliance.py` | 210 | Airspace approvals (grant/deny/revoke cascade), TFRs |
| `routes/slots.py` | 725 | FlightSlot booking, schedule, weather, reschedule, flight log, client cancel, proofs |
| `routes/billing.py` | 206 | Make-good credits, invoice issue/mark_paid/void with credit revert |
| **Total** | **3161** | |

## Coverage
- **Endpoints: 79/79** from PRD §4 (verified by decorator count).
- **State machines: 10** — Campaign, Banner, BannerRevision (PROPOSED→APPROVED→ACTIVE auto-promote with pinned 3-step propagation), AirspaceApproval (revoke cascades slots→CANCELLED_TFR), FlightSlot (9 transitions incl. weather hold/cancel), MakeGoodCredit, Pilot (auto-suspend at 3 pickup failures with slot-revert cascade), Aircraft (ground cascade), Invoice (void reverts credits), TFRRestriction.
- **Calculations: 10** — go_no_go thresholds, tiered flight-hour billing (per-line half-up → sum → discount → round; 20h/50h tiers), cancellation penalty (72h/24h inclusive boundaries), make-good waterfall (expiry then creation order), aircraft & pilot weighted selectors (600h/500h hard caps, created_at tie-break), refab trigger, seasonal capacity accounting, pickup-failure suspension, half-open TFR overlap.
- **OCC** on all three declared endpoints (`expected_campaign_version`/`expected_seasonal_capacity_version`/`expected_banner_version`, `ERR_STALE_VERSION` 412, checked last per PRD §2.7).
- **Validation pipeline** follows PRD priority order (auth → path existence → body FK existence → from-state before terminal → business rules in §3.5's pinned sequence → ownership → OCC).

## Boot verification
- Clean-boot smoke test passed: `bash start.sh` on a free port, readiness probe + `POST /btaa/bases` returned 201 with the spec'd envelope, server killed cleanly.
- Restart-pristine test passed: entity created, server killed, rebooted → prior id 404s and collections are empty (no seeding, no persistence).
- Six end-to-end suites (all passing, each against a fresh `start.sh` boot) exercised: full happy path (base→fleet→route→capacity→client→campaign→banner→revision→fabricate→approval→slot→schedule→weather→log→proof→invoice→paid→auto-COMPLETE), TFR block/waiver/adjacency, double-booking, NO_GO hold→reschedule→cancel with credit creation (30-day expiry), make-good supersede booking, invoice waterfall + void restore, penalty boundaries at exactly 72h/24h, tier discount at 21.3h, segregation of duties, pilot suspension and aircraft grounding cascades with selector re-pick, campaign cancel strictness per state, ops-run expiry boundary, pagination meta, enum/400 validation, and RBAC/ownership rejections.

## Step 7: Run Tests and Iterate — 2026-08-13T02:30:00.000Z

All 8 rounds pass 60/60. Summary (verbatim from subagent):

**Iterations run:** 2 (sweep 1: 4 deterministic failures + 1 transport flake; sweep 2 after fixes: all 8 rounds clean, 60/60 × 8).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `test_helpers/api_client.py` — added a `_request` override on `ApiClient`: sends `Connection: close` (fresh TCP connection per request, so per-test server restarts never leave a stale keep-alive connection in the pool) and retries up to 3 attempts with 0.25s backoff on `requests.exceptions.ConnectionError`/`ChunkedEncodingError`. Why: 1/8 rounds lost `test_role_not_permitted_for_endpoint_rejected` to `IncompleteRead(0 bytes read, 331 more expected)` — a server-restart/in-flight-request race under heavy concurrent host load (multiple foreign pipelines running simultaneous sweeps). Pure transport hardening; no assertion logic touched.

**Fixes applied to `test_suite/`:**
- `test_suite/test_03_campaign_lifecycle.py` — `test_campaign_completes_when_invoice_paid` and `test_campaign_completes_when_invoice_voided`: restructured setup so the invoice is ISSUED while a second slot is still BOOKED, then the second slot flies. Why: the original setup issued the invoice only after the last slot went terminal, which made the tests depend on the PRD-ambiguous zero-invoice window (vacuous truth of §3.2's "every invoice issued for the campaign is PAID or VOID" over an empty set — the PRD-only implementation completed the campaign at last-terminal-slot). The restructure exercises the verbatim §3.2 gate (unsettled invoice blocks COMPLETE; PAID/VOID releases it) identically under both reasonable readings. Assertions unchanged; the tests remain tagged to the same design instance.

**Fixes applied to `implementation/`:**
- `workspace/implementation/routes/slots.py` — `create_flight_slot`: added the parent-campaign from-state check (slot creation permitted from DRAFT/BOOKED/IN_FLIGHT; terminal COMPLETE/CANCELLED rejected with `ERR_INVALID_STATE` 409), placed after body-FK existence checks and before the §3.5 business-rule sequence, matching the PRD §2.7 pipeline order. Why: `test_cancelled_campaign_masks_tfr_violation` and `test_cancelled_campaign_masks_unapproved_airspace` (8/8 rounds each) require the §2.7 state check to pre-empt business rules; the implementation previously fell through to `ERR_TFR_BLOCKS_SLOT`/`ERR_AIRSPACE_NOT_APPROVED`.

**Diagnostic notes (STEP 1 verdicts):** all four deterministic failures traced to PRD-verbatim rules (§2.7 state-check precedence; §3.2 invoice-gated completion) — no PRD-silent tests found, no unique-derivability deletions required. The two completion tests were kept and repaired rather than deleted because the ambiguous zero-invoice window was an artifact of their setup ordering, not of the asserted rule.

## Step 8: Finalize PRD — 2026-08-13T02:40:00.000Z

Step 7 had 1 `implementation/` fix + 2 `test_suite/` fixes + 1 `test_helpers/` fix → Step 8 NOT skipped. Summary (verbatim from subagent):

Done. `workspace/PRD_FINALIZED.md` written with exactly 2 inline edits.

## Stats
- Line counts: PRD.md 307 → PRD_FINALIZED.md 307 (both edits inline within existing paragraphs); +423 chars, **+0.81%**.

## Changes
- **§3.2 — revise** — Campaign completion sentence now reads "…every invoice issued for the campaign is `PAID` or `VOID` **— a condition satisfied vacuously when no invoice has been issued for the campaign —** the campaign completes itself to `COMPLETE`." Pins the zero-invoice window the test_03 restructure exposed. Impl: `services.py:236-238` (`maybe_complete_campaign`'s `all(...)` over the campaign's invoice list is vacuously true on an empty set).
- **§3.5 — insert** — New sentence at the head of the booking-checks paragraph: "For the state-check stage of the §2.7 pipeline, creating a flight slot is treated as a transition on the parent campaign: the campaign must be in `DRAFT`, `BOOKED`, or `IN_FLIGHT`, and a creation request against a terminal campaign (`COMPLETE` or `CANCELLED`) is rejected with `ERR_INVALID_STATE` (HTTP 409) before any business rule runs." Impl: `routes/slots.py:136-144` (check placed after body-FK existence at slots.py:122-132, before the TFR/airspace/banner business-rule sequence — exactly what `test_cancelled_campaign_masks_tfr_violation` and `test_cancelled_campaign_masks_unapproved_airspace` require).

Step 7 items producing **no** PRD edit: `test_helpers/api_client.py` (pure transport hardening, no behavioral content); the test_03 restructure itself (fixture-ordering repair — its revealed ambiguity is pinned by the §3.2 edit above).

## Per-edit pre-edit search log
**Edit 1 (§3.5 from-state check).** (a) Subject: gating of flight-slot creation on parent campaign state. (b) Enumerated: `create_flight_slot` (slots.py:92-245 — confirmed the sole slot-creation site via grep for `DB["flight_slots"][` writes); sibling campaign state checks `book_campaign`/`cancel_campaign` (clients.py:151, 188 — different transitions); other nested-creation endpoints `create_banner` (banners.py:39-62), `issue_invoice` (billing.py:83-117), approval/TFR creation (compliance.py) — **none** check parent state. (c) Adjustment: wording scoped explicitly to flight-slot creation ("creating a flight slot is treated as a transition on the parent campaign") rather than a universal nested-creation rule, since banner/invoice creation under terminal campaigns is unguarded; placement phrased as "the state-check stage of the §2.7 pipeline" so it inherits §2.7's existence-before-state ordering, matching impl placement.

**Edit 2 (§3.2 vacuous-truth clause).** (a) Subject: the campaign auto-completion gate's invoice condition over an empty invoice set. (b) Enumerated: `maybe_complete_campaign` (services.py:226-240) and all six callers — slots.py:590 (flight log), services.py:289/299/328 (client/TFR/weather slot cancellation), billing.py:162 (mark_paid), billing.py:205 (void); plus the §2.11 summary sentence ("every slot is terminal and every invoice settled"), which reads consistently once §3.2 pins the vacuous reading. (c) Adjustment: clause scoped to the invoice condition only — deliberately did not pin the impl's IN_FLIGHT-only or non-empty-slots sub-gates (services.py:229-233), which Step 7 never exercised.

## Step 9: Complete PRD — 2026-08-13T03:10:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`, fully aligned to `implementation/`. Summary (verbatim from subagent):

## File stats
- Source `PRD_FINALIZED.md`: 307 lines, 53,064 chars
- `PRD_COMPLETED.md`: 311 lines, 59,996 chars
- Char delta: **+6,932** (27 edit operations; no new sections, all in-paragraph inserts/revisions)

## Counts
- **Ambiguity-pins: 34** (PRD silent → pinned to impl behavior)
- **Mismatch-revisions: 4** (PRD described behavior impl does not exhibit)

## Changes

**Ambiguity-pins (insert/revise):**
- §2.1 — insert — ambiguity — system-wide filtered listings scope entity-backed callers to their own resources (Client: own campaigns' banners/revisions/slots/logs/credits; Pilot: records naming them); pilot single-get of assessments/logs follows same rule, except an assessment naming no pilot is readable by any pilot — banners.py:166-182,309-328; slots.py:273-300,452-480,605-641; billing.py:63-77
- §2.2 — insert — ambiguity — unmatched route or unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500, both in the standard envelope — app.py:20-30
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, negative `offset` → `ERR_INVALID_REQUEST` 400 — util.py:186-214
- §2.3 — insert — ambiguity — filters apply before pagination; `has_more` true exactly when `offset + limit < total_count`; `total_count` counts the filtered set — response.py:24-31
- §2.3 — insert — ambiguity — `created_at` ties (common under the frozen logical clock) break by insertion sequence — services.py:78-80
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — services.py:49-58
- §2.5 — revise — ambiguity — clock endpoint echoes the supplied `to_iso8601` value verbatim as `current_utc` — ops.py:59-65
- §2.5 — insert — ambiguity — every server-stamped timestamp (`created_at`, `updated_at`, `api_request_timestamp`, `assessed_at_utc`, `filed_at_utc`, `submitted_at_utc`, `cancelled_at_utc`) reads the logical clock — db.py:51-66
- §2.7 — insert — ambiguity — undeclared payload fields are ignored, not rejected — util.py:64-77
- §2.8 — insert — ambiguity — a slot's capacity month is the calendar month of its `date_local`; duplicate (base, month) capacities are permitted and the earliest-created record is operative — services.py:180-182, 246-250
- §2.9 — revise — ambiguity — hobbs billable duration rounded half-up to the nearest tenth — util.py:54-56
- §2.9 — revise — ambiguity — in-season determined by the month of the slot's `date_local` (May–September inclusive) — slots.py:557-568
- §2.11 — insert — ambiguity — a parent whose recomputed counters are unchanged is not modified; its `version`/`updated_at` stand — services.py:188-223
- §3.1 — insert — ambiguity — `length_nm` may be any number; `min_banner_length_ft`, `max_tow_weight_lbs`, `hourly_rate_cents` must be integers — ops.py:99-100, 290-291
- §3.1 — insert — ambiguity — uniqueness of base `code`, `tail_number`, `certificate_number`, route `code` is descriptive, not server-enforced — ops.py:71-80, 92-115, 193-217, 283-304
- §3.1 — insert — ambiguity — lifecycle from-states pinned (ground←ACTIVE, return←MAINTENANCE, retire←ACTIVE, reinstate←SUSPENDED, deactivate←ACTIVE), all violations including the no-SCHEDULED-slots and failure-count preconditions → `ERR_INVALID_STATE` 409 — ops.py:132-187, 239-277
- §3.2 — insert — ambiguity — credit-hold capability request carries a boolean `credit_hold` field; hold check applies to PlatformAdmin too and fires before ownership, both before payload validation — clients.py:83-109
- §3.2 — insert — ambiguity — campaign booking with no BOOKED slot → `ERR_INVALID_STATE`; fixed check order: from-state → booked-slot → credit-hold → ownership → OCC — clients.py:143-180
- §3.2 — insert — ambiguity — campaign cancel: ownership check runs after the open-slot precondition — clients.py:183-218
- §3.2 — insert — ambiguity — completion evaluated only while `IN_FLIGHT`; a `BOOKED` campaign with all-terminal slots stays `BOOKED` — services.py:226-240
- §3.3 — insert — ambiguity — `banner_length_ft`/`banner_weight_lbs` are integers; revisions may be proposed against a banner in any status — banners.py:48-49, 188-216
- §3.3 — revise — ambiguity — fabricate length check covers routes of campaign slots in `BOOKED`/`SCHEDULED`/`WEATHER_HOLD`/`FLOWN` — banners.py:104-118
- §3.4 — revise — ambiguity — `stadium_tfr_waiver` accepted on routes of any kind, consulted only for `STADIUM` — compliance.py:53-55; services.py:397-407
- §3.5 — insert — ambiguity — slot-creation payload field validation runs after path resolution, before body-FK existence — slots.py:92-132
- §3.5 — revise — ambiguity — approval granted for a different route also fails as `ERR_AIRSPACE_NOT_APPROVED`; banner not required to belong to the parent campaign; make-good source not required to belong to the same campaign — slots.py:154-173; services.py:432-453
- §3.5 — revise — ambiguity — selectors' placement in the pinned order (aircraft selector immediately before the double-booking check, pilot selector after it); double-booking applies to the single selected aircraft with no fallback, occupancy = `BOOKED`/`SCHEDULED`/`WEATHER_HOLD`; no overlap constraint for pilots — slots.py:177-187; services.py:456-467
- §3.5 — revise — ambiguity — approval-window containment inclusive at both ends; missing `SeasonalCapacity` record fails as `ERR_SEASONAL_CAPACITY_EXCEEDED`; client-ownership check runs after capacity, immediately before OCC — services.py:410-414; slots.py:203-217
- §3.5 — revise — ambiguity — selector score ties break by `created_at` then insertion sequence — services.py:334-380
- §3.6 — revise — ambiguity — schedule: aircraft checked first (non-ACTIVE → `ERR_INVALID_STATE`), suspended pilot → `ERR_PILOT_SUSPENDED`, other non-ACTIVE pilot → `ERR_INVALID_STATE`; selector re-pick errors surface at scheduling — slots.py:306-354
- §3.6 — insert — ambiguity — `ceiling_ft`/`wind_kts` integers, `visibility_sm` any number; assessments accepted only from `SCHEDULED`/`WEATHER_HOLD` else `ERR_INVALID_STATE`; `assessed_by_pilot_id` = calling pilot for Pilot callers, else the slot's assigned pilot — slots.py:398-438
- §3.6 — revise — ambiguity — reschedule failures pinned: outside window → `ERR_OUTSIDE_APPROVAL_WINDOW`; hold-count of two → `ERR_INVALID_STATE` — slots.py:357-392
- §3.7 — insert — ambiguity — duplicate proof submission → `ERR_INVALID_STATE` 409; finalize has no from-state check (re-finalize succeeds) — slots.py:692-695, 724-735
- §3.8 — insert — ambiguity — invoice issuance requires no campaign state, permits duplicate periods and all-zero invoices; credit eligibility end date = last calendar day of period month; consuming slot = earliest-created unconsumed replacement naming the credit's source slot; `expired_credit_ids` listed in ascending `created_at` order — billing.py:83-117; services.py:543-547, 570-580; ops.py:386-407
- §3.8 — revise — ambiguity — penalty period membership keyed by the month of `cancelled_at_utc`; preview period supplied as `period_yyyy_mm` query param (missing/malformed → `ERR_INVALID_REQUEST`), planned lines keyed by `date_local` month, flown lines by `filed_at_utc` month, tiered discount applies to combined provisional hours, penalty/credit figures always zero and `total_cents` equals the preview subtotal — services.py:518-540; clients.py:221-242; services.py:482-515

**Mismatch-revisions:**
- §2.7 — revise — mismatch — removed the `ERR_ALREADY_TERMINAL` terminal-lockdown stage; impl never emits that error, terminal states permit no outgoing transitions so the from-state `ERR_INVALID_STATE` always surfaces — (string absent from all of implementation/)
- §3.3 — revise — mismatch — revision approval performs the three pinned steps *plus* copying `proposed_text`/`proposed_artwork_hash` onto the banner's `text_message`/`artwork_hash` (PRD had closed the enumeration at three) — banners.py:280-289
- §3.8 — revise — mismatch — ops checkpoint sweep is global across all bases; the named base is validated only for existence (PRD read as base-scoped) — ops.py:386-407
- §5 — revise — mismatch — removed the `ERR_ALREADY_TERMINAL` catalogue row and added `ERR_INTERNAL` 500 to match the impl's actual error set — app.py:20-30

## Pipeline complete — 2026-08-13T03:10:00.000Z

All 9 steps done. Final state: 60/60 tests passing across 8 parallel stability rounds; PRD_COMPLETED.md is the final contract document.

## Step 7: Test/Fix Iteration Loop — 2026-08-13T02:45:00.000Z

Ran the parallel 8-round stability sweep (`prd-bench-local-run --isolation per-test-server`, 60 tests/round).

**Iteration 1 failures (union across rounds):**
- `test_cancelled_campaign_masks_tfr_violation` + `test_cancelled_campaign_masks_unapproved_airspace` (8/8 rounds each): implementation `create_flight_slot` lacked the PRD §2.7 from-state check on the parent campaign, so business-rule errors surfaced instead of `ERR_INVALID_STATE` for a CANCELLED campaign. **Fix (implementation)**: `routes/slots.py` — added campaign from-state check (DRAFT/BOOKED/IN_FLIGHT permitted; terminal states rejected with `ERR_INVALID_STATE` 409) placed after body-FK existence and before the §3.5 business-rule sequence, matching the §2.7 pipeline order.
- `test_campaign_completes_when_invoice_paid` + `test_campaign_completes_when_invoice_voided` (8/8 rounds each): the tests' setup issued the invoice only AFTER the last slot went FLOWN, which made them depend on the PRD-ambiguous zero-invoice window (vacuous truth of "every invoice issued for the campaign is PAID or VOID" over an empty set — the PRD-only implementation completed the campaign at last-terminal-slot). **Fix (test_suite)**: restructured both tests so the invoice is ISSUED while a second slot is still BOOKED, then the second slot flies — the §3.2 completion gate (unsettled invoice blocks COMPLETE; PAID/VOID releases it) is now exercised identically under both reasonable PRD readings. Assertions unchanged; no test deleted.
- `test_role_not_permitted_for_endpoint_rejected` (1/8 rounds): transport-level flake (`IncompleteRead` mid-response) from the per-test server restart racing an in-flight request under heavy host load. **Fix (test_helpers)**: `api_client.py` — `_request` override sends `Connection: close` (fresh TCP per request, no stale keep-alive pooling across restarts) and retries up to 3 times with 0.25s backoff on `ConnectionError`/`ChunkedEncodingError`. No assertion logic touched.

**Iteration 2 sweep: all 8 rounds 60/60 passed — CLEAN.**
