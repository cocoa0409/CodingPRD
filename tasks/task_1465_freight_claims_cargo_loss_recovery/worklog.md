# Worklog — task_1465_freight_claims_cargo_loss_recovery

## Step 1: Create task directory — 2026-08-13T09:48:00.000Z

Pre-assigned directory `tasks/task_1465_freight_claims_cargo_loss_recovery/` with `workspace/` created by the invoking pipeline (Step 1 treated as DONE per invocation args).

## Step 2: Generate scaffold — 2026-08-13T10:34:38.112Z

All three scaffold files written and validated. Final lint verdict: **clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.**

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1465_freight_claims_cargo_loss_recovery/`):
- `SCAFFOLD.yaml` — §1.0–§1.7, no `scaffold_difficulty_design`/`scaffold_corner_design` keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design:`

**Counts:**
- Entities: **14** (Carrier, Lane, CarrierLaneAssignment, Shipment, Claim, ClaimDocument, LiabilityAssessment, SalvageDisposition, Appeal, Settlement, SubrogationCase, Reserve, ClaimEvent, ClaimsCalendar)
- State machines: **11** (Claim with cyclic DECLINED↔APPEALED↔UNDER_REVIEW loop and parallel filing_status × payment_status dimensions, ClaimDocument, LiabilityAssessment, SalvageDisposition, Appeal, Settlement with fork/counter/expire branches, SubrogationCase, Reserve, Carrier, Lane, Shipment)
- Endpoints: **69** (includes `POST /_clock/set_current_utc` test-driving endpoint with default 2026-08-01T00:00:00Z)
- Errors: **45**
- Roles: **8** (PlatformAdmin, ClaimsClerk, ClaimsAdjuster, ClaimsManager, SalvageCoordinator, SubrogationSpecialist, FinanceController, Any) — segregation-of-duties model
- Calculations: **8** (limitation_of_liability with 4 carrier models + lane discount + negligence step, settlement_authority tiered, claim_ratio_analytics with trailing-12m/lifetime variants, salvage_net_credit, reserve_sizing weighted, acknowledgment_late_check, claim_aging_buckets, subrogation_recovery_ratio)
- Concurrency rules: **3** OCC rules on Claim version (settle, decline, appeal)
- §1.8 difficulty instances: **18** (9 rules × 2 instances each)
- §1.9 corner instances: **28** across 7 sections (entities, state_machines, calculations, validations, endpoints, errors, roles, cross_cutting_layers, consistency_model)

**Final lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(Note: subagent required two resume nudges — first exit happened before any file was written, second during lint-fix; both resumes completed the work.)

## Step 3: Copy shared files — 2026-08-13T10:34:38.112Z

Copied `./INSTRUCTION.md` → `tasks/task_1465_freight_claims_cargo_loss_recovery/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T10:53:26.802Z

PRD generation complete. All three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1465_freight_claims_cargo_loss_recovery/workspace/PRD.md` — 335 lines. (The forbidden `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened.)

**Section list:**
- §1 Introduction (2 paragraphs, deadline/ledger pain-point angle)
- §2 Global Specifications: 2.1 RBAC, 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields, plus every list-endpoint filter param), 2.4 Common Resource Properties (incl. the `updated_at`/`version` absence for `CarrierLaneAssignment` and `ClaimEvent`), 2.5 Money/Precision/Rounding, 2.6 OCC, 2.7 Logical Clock & Scheduled Transitions, 2.8 Nested Resource Retrieval, 2.9 Validation Order, 2.10 Claim Event Log
- §3 Business Logic (9 subsections): 3.1 Carrier/Lane Administration, 3.2 Shipment Registration & Claim Intake, 3.3 Filing/Acknowledgment/Carmack Clock, 3.4 Liability Assessment & Limitation-of-Liability Pipeline, 3.5 Salvage/Reserves/Net Exposure, 3.6 Settlement Negotiation & Payment, 3.7 Decline/Appeal/Closure, 3.8 Subrogation, 3.9 Analytics & Aging
- §4 Endpoint Definitions (69 rows, 4 columns) — verified 69/69 scaffold endpoints present
- §5 Error Code Catalogue (45 rows, 2 columns)

**Coverage audit (all PASS):**
- **Contract 1 — Field-name coverage:** 121 required identifiers (115 entity fields + endpoint inputs/query params/path params + `now_iso8601`, `basis_cents`, aging bucket names, common fields), 121 present in backticks, 0 missing (verified by script with fenced-code-block masking).
- **Contract 2 — Rule coverage:** validations with priority 17/17 expressed as an explicitly ordered pipeline in §2.9 (with tie-break rationale: state before OCC, SoD before fiscal); concurrency rules 3/3 (settlements create, decline, appeal open — `expected_claim_version` + `ERR_STALE_VERSION`/412 + stale-version framing, no race language); state-machine transitions 50/50 (Claim 16, ClaimDocument 2, LiabilityAssessment 3, SalvageDisposition 2, Appeal 4, Settlement 5, SubrogationCase 9, Reserve 2, Carrier 3, Lane 1, Shipment 3) with preconditions paired to error IDs and all side effects (counter/ratio recomputes, reserve exhaustion, shipment reversion, the SUBMITTED-vs-ACKNOWLEDGED `TIME_BARRED` counter asymmetry); calculations 8/8 in precise prose (5-step liability pipeline with pinned order and floor-at-each-multiplication, tier thresholds with inclusive boundaries, both ratio formulas with max-denominator guard and TRAILING_12M/LIFETIME variants, salvage net credit, reserve sizing multipliers 1.20/1.10/1.15/1.05 with 2× cap, strict-inequality ack-lateness, aging bucket boundaries, recovery-ratio 10000 bp cap); validations 17/17 matchable to error IDs in prose; endpoint side effects 37/37 expressed; sibling branches symmetric (three withdraw sources, three subrogation settle/close sources, four liability models, four negligence flags); all enum value sets enumerated verbatim.
- **Contract 3 — §3 path purity:** 566 backtick tokens scanned in §3, 0 tokens starting with `/`, 0 bare HTTP methods, 0 method+path tokens.
- All 45 error IDs appear in §2/§3 narrative; §2.2 byte-identical to the canonical block; no fuzzy/approximating words or pseudocode operators (one ordinary-language "reason about" was reworded to "reason over" to keep the scan clean).

## Step 5: Generate unit tests — 2026-08-13T11:38:02.234Z

Generation complete. All self-checks pass.

**Files written**

**`test_helpers/`** (9 files) at `/home/ubuntu/github/CodingPRD/tasks/task_1465_freight_claims_cargo_loss_recovery/test_helpers/`:
- `types.py` — 18 enums + 14 entity TypedDicts (CarrierLaneAssignment/ClaimEvent correctly carry only `id`+`created_at`)
- `api_client.py` — 53 endpoint methods covering every PRD endpoint incl. clock, calendar, analytics
- `api_errors.py` — 45 `ApiErrorId` values with HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters + `assert_net_exposure_invariant`; integer-cents discipline per PRD §2.5
- `factories.py`, `constants.py` (TIER_2_CAP, bucket edges, Carmack defaults, etc.), `test_users.py` (9 shared role headers; distinct adjuster/manager user ids for segregation-of-duties tests)
- `fixtures.py` — 8-tier composite chain: `setup_claim_draft → submitted → acknowledged → under_review → offered → paid / declined → appealed`, plus `set_clock`/refresh helpers, all via `get_success_data`
- `__init__.py` — barrel export

**`test_suite/`** (9 files): `conftest.py` + `test_01_registration_and_intake.py`, `test_02_access_control.py`, `test_03_filing_acknowledgment.py`, `test_04_documents_and_assessment.py`, `test_05_salvage_and_exposure.py`, `test_06_settlement_lifecycle.py`, `test_07_appeal_and_recovery.py`, `test_08_analytics.py`

**Test counts**

- **Queue A (Difficulty): 17/18 instances emitted, 34 tests** (exactly 2 per instance)
- **Queue B (Corner): 27/28 instances emitted, 27 tests** (1 per instance)
- **Total: 61 tests**, collected cleanly by `pytest --collect-only`

**Skipped instances (PRD-first filter failures)**

1. **`Difficulty/resource_temporal_overlap/carrier_lane_assignment_window_overlap_rejected`** — PRD §3.1 declares only triple uniqueness ("The triple of carrier, lane, and `effective_from` must be unique"); the recipe asserts `ERR_DUPLICATE_KEY` for an overlapping window with a *different* `effective_from`, which a PRD-faithful implementation would accept. Fails unique derivability.
2. **`Corner/calculations/reserve_sizing_weighted_score`** — PRD §3.5 says the system "computes a sizing suggestion" but binds it to no observable field (Reserve carries only `amount_cents`/`posted_by_user_id`/`posted_at`/`released_at`/`state`); the asserted 15,939 value is not uniquely derivable from any response.

**Recipe-vs-PRD corrections (asserted outcome preserved, trigger aligned to PRD)**

- `error_settlement_exceeds_net_exposure` — recipe triggered at offer creation, but PRD §3.6 assigns creation-time overage to `ERR_CLAIM_AMOUNT_EXCEEDS_DECLARED_VALUE`; test triggers the asserted error at **accept time** (offer 40,000, then salvage drops net exposure to 30,000).
- `error_stale_version_on_occ_endpoint` — recipe captured the *assessment's* version and would hit the state check first; realized via reserve-post version bump while claim stays UNDER_REVIEW (PRD §2.6's own example).
- `occ_stale_version_on_appeal_create` — recipe's second appeal would hit `ERR_CLAIM_INVALID_STATE` first (claim already APPEALED); realized via salvage execution bumping version while claim stays DECLINED.
- `scheduled_action_salvage_auto_execute` — asserted via GET after clock advance (PRD §2.7 auto-execution) instead of a manual execute that would collide with `ERR_SALVAGE_INVALID_STATE` under a synchronous scheduler.
- `carrier_create_success_with_defaults` — dropped the recipe's `version == 1` assertion (PRD does not pin the initial version value).

**Self-check results**

- **Stage 1**: all modules compile; `test_helpers` imports cleanly against the installed framework.
- **Stage 2 audit (scripted)**: every test has exactly one `Design:` tag as the final docstring line; every tag resolves to a real yaml instance; all queue-A instances have 2 tests, queue-B 1; every quoted PRD citation survives whitespace-normalized literal grep of PRD.md; zero `skip`/`skipif`/`xfail` markers; zero scaffold references in generated comments/docstrings.

## Step 6: Generate implementation — 2026-08-13T11:38:02.234Z

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1465_freight_claims_cargo_loss_recovery/workspace/implementation/`):

| File | Purpose |
|---|---|
| `start.sh` | Foreground launcher; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py` |
| `requirements.txt` | `flask>=3.0` |
| `app.py` | Flask app factory, blueprint registration, envelope-shaped error handlers (ApiError/404/405/500), `app.run(host="0.0.0.0", port=$PORT)` |
| `db.py` | In-memory store (14 entity dicts, starts empty), logical clock (default `2026-08-01T00:00:00Z`, never wall clock), UUID minting, ISO-8601 3-fractional-digit formatting, datetime parsing |
| `errors.py` | `ApiError` + all 38 catalogued error ids (plus 3 uncatalogued state-error ids for carrier/lane/subrogation wrong-state, returned as 409) |
| `response.py` | `meta`/`response_type`/`data` envelope, `req_` request ids, pagination meta (`limit`/`offset`/`total_count`/`has_more`, defaults 10/0, clamped to [1,100]) |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (400 missing/malformed, 403 wrong role), JSON body + typed field validators (`ERR_INVALID_REQUEST` / `ERR_INVALID_ENUM`) |
| `services.py` | Version/`updated_at`/`concurrency_token` bookkeeping, basis-point ratios (ROUND_HALF_UP), event log, 5-step limitation-of-liability pipeline (basis → model cap → lane discount floor → negligence), settlement authority tiers (TIER_2 cap 10,000,000), reserve sizing (multiplicative 1.20/1.10/1.15/1.05, cap 2×, half-up once), clock sweeps (TIME_BARRED ×2, 14-day settlement expiry, salvage auto-execute, ACK_LATE_FLAGGED) |
| `routes_core.py` | Clock, carriers, lanes, carrier-lane assignments, shipments |
| `routes_claims.py` | Claim CRUD + submit/acknowledge/decline/withdraw/close/liability-preview |
| `routes_docs_salvage.py` | Documents (verify/reject), assessments (create/approve), salvage (create/execute/cancel) |
| `routes_negotiation.py` | Appeals (open/escalate/decide), settlements (create/accept/counter/reject/withdraw) |
| `routes_recovery.py` | Subrogation lifecycle, reserves, claim event log |
| `routes_analytics.py` | Calendar rows, carrier/lane claim-ratio (with TRAILING_12M window), claim aging buckets |
| `serializers.py` | Per-entity public field projections (assignments/events correctly omit `updated_at`/`version`) |

**Endpoint count:** all **69 endpoints** from the scaffold §1.5 table implemented and registered (verified against Flask's URL map).

**State storage:** in-memory only — module-level dicts in `db.py`, empty on every boot; no seeding, no disk I/O, no carry-over between `start.sh` restarts (verified: fresh process reports `total_count: 0`).

**Boot contract:** `bash start.sh` runs the server in the foreground via `exec`, binds `0.0.0.0`, listens on `$PORT` (default 10000) — verified live with `PORT=19999 timeout 6 bash start.sh` serving HTTP 200.

**Verification:** two custom end-to-end suites (52 + 62 checks) exercised the full claim lifecycle, all four liability models' pipeline math (incl. lane-discount floor ordering), OCC `ERR_STALE_VERSION` (412), segregation-of-duties, authority tiers TIER_1/2/3 (incl. manager-rejected TIER_3), reserve exhaust/release, partial vs full payment (`CLOSED_WITH_PAYMENT/PARTIAL` vs `PAID/PAID_IN_FULL`), appeal rounds to exhaustion, withdraw counter decrements, clock-driven TIME_BARRED/settlement-expiry/salvage-execute/ack-late sweeps, subrogation ratio cap at 10000 bp, and left-to-right nested 404s. The three initially failing checks were arithmetic errors in my own test expectations (reserve suggestion 472500 = 450000 × 1.05 lane multiplier; partial-accept classification; salvage over-credit flooring at 0) — each re-verified with corrected expectations, all passing.

## Step 7: Run tests and iterate — 2026-08-13T12:08:28.565Z

All 8 parallel rounds report `passed == total` (61/61, 0 failures, 0 errors). The sweep is fully green — exiting with the required Summary block. (Orchestrator verified all 8 `results.{1..8}.json` files independently: 61/61 × 8.)

---

**Iterations run:** 2 (iteration 1: 51/61 passing in all 8 rounds with 10 deterministic failures; iteration 2 after fixes: 61/61 in all 8 rounds).

**Tests deleted:** None. Every failing test asserted rules verbatim-covered by PRD; all failures were test-side setup bugs fixed per STEP 2.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — added `create_salvage_payload` import and a new composite fixture `setup_claim_under_review_with_pending_salvage(salvage_specs, advance_clock_to, **kwargs)`. Why: PRD §2.7 mandates that advancing the logical clock executes any due salvage disposition whose claim is in an executable state ("executed by the system exactly as if a coordinator had executed it by hand"), and §3.5 requires the disposition "still be SCHEDULED (otherwise ERR_SALVAGE_INVALID_STATE)". The old test setups advanced the clock past `scheduled_at` while the claim was UNDER_REVIEW/OFFERED/DECLINED, so the PRD-mandated sweep pre-empted the manual execute under test. The helper schedules dispositions while the claim is ACKNOWLEDGED (non-executable, so the sweep leaves them SCHEDULED), advances the clock past `scheduled_at`, then walks the claim to UNDER_REVIEW via verify+assess (no clock advance, so no sweep fires) — the only PRD-consistent window in which the manual-execution path is reachable.

**Fixes applied to `test_suite/`:**
- `test_03_filing_acknowledgment.py` (`test_resubmit_after_deadline_reports_state_error`, `test_submit_after_filing_deadline_rejected`) — fixtures passed `carmack_filing_days: 30`, but PRD §3.1 states verbatim the 270-day filing window is "a statutory floor that a contract may lengthen but never shorten", so the implementation's rejection of sub-floor windows is PRD-traceable and the fixture request was PRD-inconsistent. Fixed to keep the default 270-day window and advance the clock past `ship_date + 270d` (to 2027-03-01) instead. Assertions unchanged.
- `test_05_salvage_and_exposure.py` (`test_salvage_execute_computes_net_credit_and_updates_claim`, `test_salvage_execute_appends_event_and_bumps_version`, `test_salvage_execute_at_scheduled_time_succeeds`, `test_net_exposure_reconciles_across_sequential_salvage`) — restructured onto the new fixture so the manual-execution assertions (net-credit math, SALVAGE_POSTED event, version bump, inclusive "at or past scheduled_at" boundary, additive credit reconciliation) run in the PRD-consistent window. Assertions unchanged.
- `test_06_settlement_lifecycle.py` (`test_accept_above_current_net_exposure_rejected`, `test_salvage_credit_offsets_settlement_without_double_count`, `test_partial_settlement_lands_closed_with_payment`) — dropped the manual `execute_salvage` call after the clock advance; the §2.7 sweep itself posts the salvage credit (claim is OFFERED/UNDER_REVIEW, both executable states), producing the identical ledger state. Assertions unchanged.
- `test_07_appeal_and_recovery.py` (`test_appeal_with_stale_claim_version_rejected`) — dropped the manual execute; the §2.7 sweep execution on the DECLINED claim advances the claim version, which is exactly the "another writer advanced it" hazard §2.6 names ("executing a salvage credit"). Added a guard assertion that the sweep bumped the version before the stale-version appeal assertion. Error assertion unchanged.

**Fixes applied to `implementation/`:** None. The implementation was PRD-faithful in both diagnosed clusters: the `carmack_filing_days >= 270` floor traces to PRD §3.1's "statutory floor that a contract may lengthen but never shorten", and the synchronous salvage auto-execution on clock advance traces to PRD §2.7's "advancing the clock drives … salvage execution … exactly as if a coordinator had executed it by hand" (corroborated by the already-passing `test_salvage_auto_executes_when_clock_reaches_scheduled_at` in the same test file).

## Step 8: Finalize PRD — 2026-08-13T12:20:54.330Z

Both edits are in place and the diff confirms exactly two inline sentence insertions, nothing else. Final verification of consistency is done — here is the summary.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1465_freight_claims_cargo_loss_recovery/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 335 lines; PRD_FINALIZED.md = 335 lines; 0.0% line delta (both edits are inline sentence insertions into existing paragraphs; no sections added or removed).

### Changes (one bullet each)

- **§3.1 (Carrier and Lane Administration)** — insert — appended "A registration that supplies a `carmack_filing_days` below that floor is rejected with `ERR_INVALID_REQUEST` (HTTP 400)." after the "statutory floor" sentence — pins the enforcement mechanism and error code that the PRD left unstated — `implementation/routes_core.py:76-79`.
- **§2.7 (The Logical Clock and Scheduled Transitions)** — insert — extended the fourth sweep family with "The system's execution honors the same preconditions as a coordinator's manual execution (§3.5), so a due disposition whose claim is not at that moment in a state that admits salvage execution is left `SCHEDULED` — neither executed nor cancelled — and is reconsidered on each subsequent advance of the clock." — pins the sweep's skip-and-retry behavior in non-executable claim states, which PRD did not determine — `implementation/services.py:255-260` (gate), `implementation/services.py:15` (executable-state set), `implementation/routes_core.py:44` (sweep fires only on clock advance).

Step_7 items tracing to these edits: the `test_03` fixture fixes (sub-floor `carmack_filing_days: 30` rejection) → Edit 1; the `test_helpers/fixtures.py` composite fixture plus the `test_05`/`test_06`/`test_07` restructurings (sweep pre-emption of manual execution, sweep-posted credits, sweep-driven version bumps) → Edit 2. No implementation fixes existed to document; no tests were deleted.

### Per-edit pre-edit search log

**Edit 1 (§3.1 carmack_filing_days floor):**
- (a) Subject: validation/enforcement of the 270-day `carmack_filing_days` floor.
- (b) Paths enumerated and read/grepped: `routes_core.py:71-79` (`opt_int` read, 270 default, `filing_days < 270 → ERR_INVALID_REQUEST` 400 — the only validation site; confirmed via the §4 endpoint table and route grep that no carrier PATCH/PUT exists, so registration is the sole place the window is set), `routes_core.py:98` (storage), `serializers.py:16` (serialization), `routes_claims.py:82` and `:162` (deadline computation at claim open and at submit — read-only consumers, unaffected), `middleware.py:105-108` (`opt_int` type behavior).
- (c) Wording adjustment: scoped strictly to `carmack_filing_days` and to rejection-at-registration; deliberately silent on `carmack_acknowledgment_days > 0` and `max_auto_settle_cents >= 0` (same `if` in impl) since no step_7 item traces to them; "below that floor" preserves the inclusive boundary at exactly 270 that `filing_days < 270` exhibits.

**Edit 2 (§2.7 salvage sweep):**
- (a) Subject: clock-driven salvage auto-execution and its claim-state gate.
- (b) Paths enumerated and read/grepped: `services.py:212-274` (`run_scheduled_sweeps`; salvage loop at 255-260 skips non-executable claims, leaves them `SCHEDULED`, re-loops every advance), `services.py:196-209` (shared `execute_salvage` core used by sweep and manual paths), `services.py:15` (`SALVAGE_EXECUTABLE_STATES` = §3.5's list verbatim), `routes_core.py:38-45` (`set_clock` is the sole caller — sweep runs only on clock advance, never on claim-state change), `routes_docs_salvage.py:246-280` (scheduling has no claim-state gate — new sentence makes no claim about scheduling), `routes_docs_salvage.py:301-316` (manual execute, same three preconditions — §3.5 text left verbatim), `routes_docs_salvage.py:319-329` (cancel — unaffected; "neither executed nor cancelled" describes only the sweep's inaction and does not forbid manual cancel).
- (c) Wording adjustment: phrased as "not at that moment in a state that admits salvage execution" (defers to §3.5's enumeration rather than restating it, staying consistent with the OFFERED- and DECLINED-state sweep executions exercised in test_06/test_07) and "reconsidered on each subsequent advance of the clock" (avoids any implication that the disposition auto-executes when the claim later reaches an executable state without a clock advance — the new fixture walks ACKNOWLEDGED→UNDER_REVIEW with no clock advance and the disposition must stay `SCHEDULED`).
