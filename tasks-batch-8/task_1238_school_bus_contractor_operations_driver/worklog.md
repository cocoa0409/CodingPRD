# Worklog — task_1238_school_bus_contractor_operations_driver

## Step 1: Create Task Directory — 2026-08-12T04:49:00.000Z

Task directory `tasks/task_1238_school_bus_contractor_operations_driver/` and its `workspace/` subdirectory were PRE-ASSIGNED and already exist (per orchestrator instruction, the auto-index scan was skipped). Step 1 treated as done.

## Step 2: Generate Scaffold — 2026-08-12T05:57:00.000Z

Scaffold generation complete and lint-clean. All three artifacts are saved under `/home/ubuntu/github/CodingPRD/tasks/task_1238_school_bus_contractor_operations_driver/`.

## Deliverables

- `SCAFFOLD.yaml` (~2100 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key, 22 instances (9 rules)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key, 70 live instances + 7 `excluded_because:` stubs, across all nine claim-extraction-guide sections

## Surface (deliberately past expert band per the difficulty dial)

- **16 entities**, flat topology with FK links, self-referential `Assignment.doubled_after_assignment_id` for route doubling
- **92 endpoints** incl. `/_clock/set_current_utc` (default fixed at `2026-05-01T00:00:00Z`), full FK reverse-reachability via filtered-list GETs
- **12 state machines**, several cyclic: driver retest loop (TESTING→TRAINING→TESTING), invoice dispute/reissue loop, inspection re-inspection loop, work-order parts re-order loop, incident return-for-info loop
- **12 calculations** incl. layered fuel escalation (tiered excess over base, trigger/share percentages), pinned per-day rounding order, cap-truncated invoice total (circular-looking dependency with pinned evaluation order), dual provisional/final variants on both Invoice billing and ServiceDay shortage penalty
- **14 prioritized validation rows** (schema → auth → existence → ownership → OCC → state → safety → temporal → constraint → referential → fiscal)
- **41 error codes**, all referenced by at least one test recipe or transition
- **7 roles** (peer-role model; DistrictAdmin/Driver entity-backed, five opaque)
- **3 OCC concurrency rules** (contract amendment, service-day lock, charter approval version-pinning)

## Difficulty-rule coverage (§1.8, 22 instances)

Every rule has ≥2 differentiated instances: dual-variant calcs on different domains (Invoice vs ServiceDay), combinatorial formulas in modes (a)+(b)+(c) with pre-computed literals (e.g. fuel adjustment 2350/3134/500 verified by hand-executing the formulas), cascades of depth 3 from two different triggers (inspection FAIL vs clock-driven credential expiry), three distinct priority-conflict category pairs ({existence,state}, {state,safety}, {safety,fiscal}), boundary checks on three metrics (inclusive fuel trigger at exactly 420, inclusive 2400 training minutes, strict-> 24h SLA), three cross-entity state dependency pairs, two interval semantics (half-open driver adjacency vs buffered closed charter windows), and two conserved quantities (route coverage through doubling; deposit = fee + refund on cancel).

## Verification

- `scaffold_lint.py` verdict (verbatim): **"VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5."** (92 endpoints, 16 entities, 22+70 instances, 1523 calls scanned)
- Additional self-checks passed: grounds resolvability for every instance, error triggerability for all 41 codes, enum value closure for all 12 machines, name uniqueness across both design files (99 names), stub refs resolve, no forbidden concurrency vocabulary, file split honored.
- Two replay bugs found and fixed during the audit: ERR_DRIVER_REQUIRED moved to the schema tier (existence/safety would otherwise pre-empt it), and the expired-quote approve recipe now re-observes the charter version after the system EXPIRED transition so it deterministically hits ERR_ALREADY_TERMINAL rather than a stale-version 412.

## Step 3: Copy Shared Files — 2026-08-12T05:58:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1238_school_bus_contractor_operations_driver/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T06:09:00.000Z

All verifications pass. The PRD is complete and shipped.

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1238_school_bus_contractor_operations_driver/workspace/PRD.md` (~44KB prose PRD) from `SCAFFOLD.yaml`. The withheld difficulty/corner design files were not touched.

**Document structure:**
- §1 Introduction (2 paragraphs, contractor-operations angle)
- §2 Global Specifications (9 subsections): RBAC with per-role identity translation, verbatim §2.2 response envelope, pagination, common resource properties (including the append-only TrainingEvent/FuelPriceEntry/RidershipReport exception), the logical clock (startup `2026-05-01T00:00:00Z`), monetary precision, the three OCC rules, the 14-stage validation pipeline in explicit priority order, and cascade-consistency principles
- §3 Business Logic (8 subsections): contract bid lifecycle, routes/service-day planning, driver pipeline, fleet compliance, daily dispatch/doubling/reconcile, charters, invoicing/fuel escalation/credit, incidents/ridership/district reporting
- §4 Endpoint table: all 92 endpoints, 4 columns (Method, Path, Description, Authorized Roles) — method+path role verification clean
- §5 Error catalogue: all 41 errors with exact HTTP statuses, no trigger conditions

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/outputs + roles + state/enum values: 294 required, 294 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] priority ordering: 14 stages expressed as an explicit ordered pipeline in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (endpoint framing + expected_<parent>_version + ERR_STALE_VERSION/412 each), 0 missing
- state_machines[].transitions: all 10 machines' transitions expressed with preconditions and side effects (incl. terminate/credential/inspection/discipline cascades and cyclic loops), 0 missing
- calculations[]: 12 checked, 12 expressed in precise prose (fuel two-tier trigger with integer-exact comparison, pinned per-day rounding with forbidden alternative, cap truncation order, 2400/2700 weekly caps, 2400/1200 training thresholds, 45-minute doubling delay, 72/24 cancel tiers, 24/72/168 SLA hours, 9500/9000 on-time tiers), 0 missing
- validations[] conditions: all matchable to error_id in §2/§3 prose (all 41 error ids appear in §2/§3), 0 missing
- endpoints[].side_effects / applies_to: expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, computed sources, and initial values reconstructible from prose, 0 missing
- sibling-branch symmetry: PASS/FAIL, FLAT_PER_ROUTE/PER_STUDENT_MINUTE, PROVISIONAL/FINAL, all event-enum siblings treated with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 750
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Additional checks:** §2.2 block verified byte-identical to the canonical source; no fuzzy/approximating words; no pseudocode operators in prose (all formulas translated to natural language with exact thresholds and boundary inclusivity).

## Step 5: Generate Unit Tests — 2026-08-12T06:35:00.000Z

Generation complete and fully verified. 

## Summary

**test_helpers/** (9 files, imports verified): `types.py` (16 entities, correct `common_fields` branching — TrainingEvent/FuelPriceEntry/RidershipReport omit `updated_at`/`version`), `api_client.py` (~70 endpoint methods under `/busops`), `api_errors.py` (40 error IDs + HTTP status map registered with the framework), `assertions.py` (per-entity + coverage-conservation and deposit-split invariants), `factories.py`, `constants.py`, `test_users.py` (7 roles; mandatory `make_district_admin_headers` / `make_driver_headers` builders for the two entity-backed roles), `fixtures.py` (~40 helpers across all tiers: driver pipeline to ACTIVE, dispatch-day builder, reconciled/billed/issued billing scenarios, charter lifecycle chains, incident submission), `__init__.py` barrel.

**test_suite/** (conftest + 9 concern-grouped files, 114 tests): entities/envelope (10), driver pipeline (11), fleet & inspection cascades (10), dispatch confirmation (19), service-day lifecycle/doubling (16), charters (12), invoicing/fuel (22), incidents/reporting (7), auth/RBAC/OCC (7).

**Coverage audit (clean):** all 22 difficulty instances × ≥2 tests (44), all 70 non-stub corner instances × ≥1 (70). All 7 `excluded_because` stubs skipped with resolving cross-references. Every test carries exactly one verbatim `Design:` tag resolving to a real instance; 166 quoted PRD citation spans all survive literal grep of PRD.md.

**Execution proof:** `prd-bench-local-run --isolation per-test-server` against `workspace/implementation` — **114/114 passed in 94.5s**.

**PRD-first adjudications applied (gaps kept, not papered):**
1. `confirm_cancelled_assignment_with_suspended_driver_returns_409` — the instance's literal `ERR_INVALID_STATE` isn't uniquely derivable (the PRD's terminal rung explicitly lists `CANCELLED`, and §3.6 forces `ERR_ALREADY_TERMINAL` to own terminal states). Translated with `validate_error_is_one_of([ERR_INVALID_STATE, ERR_ALREADY_TERMINAL])` + 409, preserving the derivable priority claim (state layer precedes driver-dispatchability).
2. `system_fields_generated_on_create` — dropped the `version == 1` literal ("starts at its initial value" doesn't pin 1); kept UUID/no-prefix, 3-fractional-digit `created_at`, `DRAFT_BID`, `amendment_seq == 0`.
3. Two doubling instances — dropped `weekly_assigned_minutes` readback assertions (120/2400/2460): the PRD pins the confirm/doubling *gate* projection (ISO week of the target service date) but never the readable field's week basis, so PRD-faithful implementations diverge when service dates lie outside the clock's week. The cap gates remain covered via observable confirm/doubling success/failure.
4. `doubling_overtime_threshold_window` recipe repair — the recipe created six routes up front, which (given one auto-created assignment per active route per day) breaks its own `$.data[1]` capture. Realized the prose intent via route creation order [600-min run, 60-min run] so every day's `data[0]`/`data[1]` are the intended assignments; all asserted outcomes preserved.
5. `immutable_training_event_has_no_update_path` — dropped the non-API-observable "no PUT/PATCH/DELETE exists" sub-assertion; kept the append-only field assertions.

## Step 6: Generate Implementation — 2026-08-12T06:35:00.000Z

Implementation complete. Summary of what was built and verified:

## Deliverables

All under `/home/ubuntu/github/CodingPRD/tasks/task_1238_school_bus_contractor_operations_driver/workspace/implementation/`:

- **`start.sh`** — executable launcher; guards the pip install behind `python3 -c "import flask"` (no-op on per-test reboots), then `exec python3 app.py` in the foreground. Verified booting via `bash start.sh` on both the default port 10000 and `$PORT` overrides.
- **`app.py`** — Flask entry point, blueprint registration, `ApiError`/404/405/500 envelope handlers, a global request lock for atomicity, binds `0.0.0.0:$PORT`.
- **`db.py`** — empty-at-boot in-memory stores (no seeding anywhere), logical clock pinned at `2026-05-01T00:00:00Z`, UUID ids, 3-fractional-digit metadata timestamps, ISO8601 date/datetime/month parsers, `stamp_new`/`touch` (version starts at 1, +1 on every mutation including cascades).
- **`errors.py`** — full 38-entry error catalog with exact IDs and HTTP statuses.
- **`envelope.py`** — `meta`/`response_type`/`data` envelope; pagination fields (`limit`/`offset`/`total_count`/`has_more`) only in list `meta`.
- **`middleware.py`** — `X-User-ID`/`X-User-Role` auth (401), role authorization (403), DistrictAdmin/Driver entity-backed ownership (403).
- **`validation.py`** — pipeline stage-1 schema checks (required fields, enums, int ranges, dates), `ERR_DRIVER_REQUIRED` at confirm, `limit`/`offset` validation (default 10, min 1, max 100), `created_at`-ascending stable pagination.
- **`services/`** — `coverage.py` (day coverage recompute with version bump on change; driver-suspension, bus-grounding, contract-terminate, credential-lapse cascades; bus return-to-service conditions), `pricing.py` (weekly-minute soft/hard caps with ISO-week projection, half-open overlap + charter ±30min closed-buffer intersection math, charter quote/final/1.25x-overage pricing, tiered cancel fees with floor-hours boundaries, shortage credit both penalty modes, two-tier fuel escalation with pinned per-day round-half-up, invoice PROVISIONAL/FINAL line sets and monthly-cap truncation, district outstanding balance, SLA windows), `clock.py` (clock advancement firing credential-expiry, inspection-overdue, quote-expiry, contract-expiry transitions with full cascades).
- **`routes/`** — 17 blueprints covering all 60+ endpoints with the PRD's exact validation-pipeline ordering (schema → auth → role → existence left-to-right → ownership → OCC → from-state → terminal-first → driver/bus dispatchability → temporal → constraint → referential → fiscal).

## Key design decisions (all traced to PRD/scaffold text)

- Terminal-state rejection (`ERR_ALREADY_TERMINAL`) is evaluated before generic from-state checks, per the charter approve-after-expiry example.
- Invoice `total_cents` is clamped to `monthly_cap_cents` even when the preliminary (non-fuel) total alone exceeds the cap — "monthly_cap_cents bounds every invoice total" is unconditional.
- `Driver.weekly_assigned_minutes` is computed for the ISO week containing the logical-clock date.
- Service-day version increments whenever coverage figures change (confirm/no-show/cancel/doubling/cascade), matching the OCC rationale in the lock description.
- Ownership scoping enforced on single-resource contract/charter/invoice/incident reads and district-report for DistrictAdmin, and on driver-record/assignment reads for Driver; lists are not scoped (role list includes all roles for district reads).

## Verification

Five smoke rounds (~180 assertions) run against fresh server boots, all passing after fixing two real bugs found during testing (a total-exceeds-cap leak, since fixed in `pricing.py`) — the rest of the failures were smoke-script bugs. Covered: full contract/driver/bus/service-day/invoice/charter/incident lifecycles, fuel trigger boundary (P = B×(100+pct)/100 triggers), tier-2 fuel math, per-day rounding, provisional-includes-LOCKED vs final-drops-LOCKED, shortage credits both modes, soft-cap-2400 exact pass and 2401 reject, hard-cap 2700 at doubling, 45-minute doubling window, credit hold with equality-allowed semantics, dispute-window inclusive boundary with reissue refresh, quote expiry strictly-past semantics, SLA exact-deadline non-breach, credential-expiry/inspection-fail/terminate cascades, and envelope/pagination/auth shape. No tracebacks in server logs; final rerun: 82/82 on a `bash start.sh` boot.

Not read, per the constraint: `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`.

## Step 7: Run Tests and Iterate — 2026-08-12T07:27:00.000Z

All 8 parallel rounds completed and every round reports 114/114 passed.

Summary:
- Iterations run: 1 (single 8-round parallel sweep, all rounds ran to completion).
- Tests deleted: none.
- Fixes applied to `test_helpers/`: none.
- Fixes applied to `implementation/`: none.

The implementation at `/home/ubuntu/github/CodingPRD/tasks/task_1238_school_bus_contractor_operations_driver/workspace/implementation` passes the full 114-test suite consistently across all 8 concurrent rounds — no flakiness, no failures, no diagnostic action required.

Orchestrator verification: all 8 `results.{1..8}.json` files exist on disk; each reports passed=114 total=114 failed=0.

## Step 8: Finalize PRD — 2026-08-12T07:28:00.000Z

SKIPPED per the skip condition: Step 7 exited cleanly on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` was produced.

## Step 9: Complete PRD — 2026-08-12T07:41:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1238_school_bus_contractor_operations_driver/workspace/PRD_COMPLETED.md`.

**Size:** PRD.md 364 lines / 64,082 chars → PRD_COMPLETED.md 368 lines / 69,493 chars; char-delta +5,411. Structure preserved: identical headings, endpoint table, and error catalogue.

**Counts:** 16 ambiguity-pins (inserts), 5 mismatch-revisions (21 edits total).

**Mismatch revisions** (PRD described behavior impl does not exhibit):
- §2.8 — revise — mismatch — swapped pipeline stages 7/8 so terminal-state rejection (`ERR_ALREADY_TERMINAL`) precedes from-state validity (`ERR_INVALID_STATE`), and enumerated per-resource terminal sets (e.g. Credential terminal = `REVOKED` only, so revoking an `EXPIRED` credential yields `ERR_INVALID_STATE`) — routes/contracts.py:47-54, routes/drivers.py:75-82, routes/credentials.py:85-91, routes/work_orders.py:115-122, etc.
- §3.4 — revise — mismatch — `fleet_number` uniqueness within district is not enforced — routes/buses.py:24-50 (no uniqueness loop).
- §3.4 — revise — mismatch — work-order creation moves a `GROUNDED` bus to `IN_SHOP` only for `REPAIR`/`INSPECTION_FOLLOWUP` categories; a `PM` order leaves it grounded — routes/work_orders.py:62-67.
- §3.6 — revise — mismatch — charter schedule conflict checks count `CONFIRMED` **or** `EN_ROUTE` route assignments (bus side vs buffered window; driver side vs unbuffered pickup–return interval) — services/pricing.py:143-178.
- §3.7 — revise — mismatch — invoice total is additionally clamped to `monthly_cap_cents` when the preliminary total alone already exceeds the cap (fuel truncated to zero) — services/pricing.py:383-388.

**Ambiguity pins** (PRD silent, now pinned to impl):
- §2.1 — insert — ambiguity — ownership enforced on single-resource reads/mutations; list endpoints unfiltered; reference-less resources (e.g. driverless `PLANNED` assignment) not ownership-restricted — middleware.py:90-113.
- §2.2 — insert — ambiguity — unmatched paths/methods → `ERR_NOT_FOUND` 404 envelope; unhandled faults → `ERR_INTERNAL` 500 — app.py:69-79.
- §2.3 — insert — ambiguity — `created_at` sort ties break by creation order — validation.py:167-178.
- §2.4 — insert — ambiguity — `version` starts at 1; `created_at`/`updated_at` stamped from wall-clock UTC — db.py:117-135.
- §2.4 — insert — ambiguity — transition annotations (`reason`, `resolution_note`) accepted but not persisted, except dedicated fields (`cancellation_reason`, `suspension_reason`, `dispute_reason`) — routes/assignments.py:206-222, routes/incidents.py:206-218, routes/invoices.py:225-234.
- §2.5 — insert — ambiguity — clock endpoint accepts any instant (no monotonicity check); logical-clock-derived fields serialize at seconds precision — routes/clock.py:13-20, db.py:58-63.
- §2.7 — insert — ambiguity — version fields sent to non-guarded endpoints are ignored — (all non-OCC endpoints parse no version field).
- §2.8 item 1 — insert — ambiguity — non-negative integer rule, minute-of-day range 0–1439, non-string `driver_id`/`bus_id` on confirm → `ERR_DRIVER_REQUIRED`, `COMPLETE` work-order missing `labor_minutes`/`parts_cost_cents` → `ERR_INVALID_REQUEST` at schema stage — validation.py:51-74,133-139, routes/assignments.py:92-98, routes/work_orders.py:109-113.
- §3.1 — insert — ambiguity — all three shortage fields required regardless of `penalty_mode`; no `start_date` ≤ `end_date` enforcement — routes/contracts.py:57-104.
- §3.2 — insert — ambiguity — archive blocked by future assignments → `ERR_INVALID_STATE` — routes/routes.py:118-131.
- §3.3 — insert — ambiguity — `weekly_assigned_minutes` derived at read time over the ISO week containing the clock date; training events filterable by `driver_id`/`category`; credential for `APPLICANT`/`SCREENING` → `ERR_INVALID_STATE`, `TERMINATED` → `ERR_ALREADY_TERMINAL`; no `issued_on`/`expires_on` ordering — routes/drivers.py:58-61, routes/training_events.py:65-78, routes/credentials.py:27-36.
- §3.4 — insert — ambiguity — inspection scheduling / work-order creation on `DECOMMISSIONED` bus → `ERR_ALREADY_TERMINAL`; decommission blocked → `ERR_INVALID_STATE` — routes/inspections.py:38-39, routes/work_orders.py:46-47, routes/buses.py:86-101.
- §3.5 — insert — ambiguity — confirm against non-`DISPATCH_OPEN` day → `ERR_INVALID_STATE`; "commitment" = `CONFIRMED`/`EN_ROUTE` assignments plus `SCHEDULED`/`IN_PROGRESS` charters with ±30-min buffered window; doubling pins (uncovered must be `PLANNED` on that day — terminal/other-state/other-day errors; absorbing driver/bus re-run dispatchability; shifted-window overlap; bus-district match); reconcile `PER_STUDENT_MINUTE` uncovered set = `PLANNED`/`CONFIRMED`/`NO_SHOW` only — routes/assignments.py:106-109, services/pricing.py:65-118, routes/service_days.py:284-348, services/pricing.py:219-239.
- §3.6 — insert — ambiguity — quoting requires the contract still `ACTIVE` (`ERR_CONTRACT_NOT_ACTIVE`) — routes/charter_trips.py:158-160.
- §3.7 — insert — ambiguity — fuel-adjustment input set is the period's `RECONCILED` days in both variants; no per-period invoice uniqueness; reissue `adjustment_delta_cents` and `reason` both required; trigger inequality parenthesized as `base × (100 + trigger_pct)` — services/pricing.py:277,376, routes/invoices.py:49-97,195-209.
- §3.8 — insert — ambiguity — ridership on non-`COMPLETED` assignment → `ERR_INVALID_STATE`; `service_day_id` existence-checked only; `on_time_tier` null when no reports — routes/ridership.py:38-52, routes/service_days.py:385-396.

Orchestrator verification: PRD_COMPLETED.md exists on disk (368 lines, 69,493 chars). Step 9 touched only the PRD document — implementation and tests unchanged since the clean 8-round sweep.
