# Worklog — task_0278_internet_broadband_provisioning

## Step 1: Create task directory — 2026-06-10T02:52:38.000Z

Created `tasks/task_0278_internet_broadband_provisioning/` and `tasks/task_0278_internet_broadband_provisioning/workspace/` (pre-assigned directory, no tasks/ scan). Verified project root has `INSTRUCTION.md` and `skills/`.

## Step 2: Generate scaffold — 2026-06-10T03:14:49.000Z

All three scaffold artifacts are generated, internally consistent, and pass the lint clean.

Generated three scaffold artifacts for **task_0278_internet_broadband_provisioning** (Internet/Broadband Service Provisioning) at the **Expert** difficulty band. Files: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key).

`scaffold_lint.py` verdict: clean — all 460 §1.8/§1.9 calls conform to §1.5; every §1.1 FK has reverse-reachability in §1.5.

Scaffold contents:
- 13 entities: ServiceAddress, ServicePlan, Account (OCC anchor), EquipmentUnit, ServiceOrder, InstallSlot, Technician, InstallAppointment, BillingCycle, UsageRecord, OutageEvent, AccountCredit, TransferRequest. Flat topology with cross-aggregate and polymorphic FKs.
- 7 state machines: Account (PENDING→ACTIVE→{SUSPENDED↔ACTIVE, DISCONNECTED, TRANSFERRED}), ServiceOrder (branching fork-join: TECH_INSTALL vs SELF_INSTALL → ACTIVATED), EquipmentUnit (cyclic: RETURNED→IN_INVENTORY→LEASED re-lease loop), BillingCycle (parallel: billing_state × throttle_state), OutageEvent, TransferRequest, InstallAppointment.
- 6 calculations (4 with variants): overage_charge (tiered+cap, estimate vs final dual-variant), outage_credit (interval-merge proration), lease_proration_credit (decay, standard vs lost-reversal), early_termination_fee (decay, charged vs waived), monthly_bill_total (pinned-order waterfall with subtotal-keyed promo), serviceable_speed_check.
- 16 validations (priority-ordered, 8 categories) and 2 concurrency rules (OCC on Account.version for appointment booking and plan change).
- 61 endpoints (incl. one /_clock test-driving endpoint), 22 errors, 4 roles (Customer, ProvisioningAgent, NetworkOps, Dispatcher — peer_roles model, all opaque identity).

Design coverage:
- §1.8: all 9 difficulty rules × 2 instances = 18 instances, every numeric assert pre-computed as a literal (e.g., overage estimate 1000 vs final 2890; ETF 15000; bill total 12327; lease refund 1000; outage credit 62/187).
- §1.9: 29 active corner instances + 7 excluded_because stubs across all 9 claim-extraction-guide sections; every stub cites an existing §1.8 instance.

Expert-band targeting: density over volume — 13 tightly-coupled entities driving 3+ dual-variant calculations across different domains (BillingCycle metering vs Account contract), a depth-3 disconnect cascade and depth-2 activation cascade from different triggers, two compensating invariants over different conserved quantities (ETF vs lease fee), two temporal-overlap rules with different interval semantics (slot aggregate-capacity vs technician buffered-interval), parallel state dimensions on BillingCycle plus a cyclic EquipmentUnit machine, OCC on the parent version, and boundary-precision edges (strict > data-cap crossing at 1000/1001, inclusive >= SLA at 239/240) on different metrics and endpoints. Endpoint count (61) deliberately runs above the nominal Expert ceiling because the scenario spans eight distinct sub-workflows each needing create+read+list+lifecycle coverage; difficulty comes from coupling density, not surface size.

## Step 3: Copy shared files — 2026-06-10T03:15:29.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0278_internet_broadband_provisioning/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-06-10T03:21:28.000Z

Output: `workspace/PRD.md` (311 lines). Generated purely from this task's SCAFFOLD.yaml; neither design YAML was read.

Structure: 5 top-level sections; 11 §2 subsections; 12 §3 subsections; §4 table 61 endpoint rows (Method, Path, Description, Authorized Role(s)); §5 table 22 error rows.

Hard Contracts all PASS:
- Field coverage (Contract 1): 68 required identifiers (63 entity fields, 55 input identifiers, 1 path param) all present, 0 missing.
- Rule coverage (Contract 2): all 22 error IDs surfaced; all 29 state values + 60 enum values in backticks; 5 calculations in precise prose (overage tier ladder 50/30/20¢ + 6000¢ cap, outage credit interval-merge + 240-min threshold, lease proration, ETF decay, monthly_bill_total 8-step waterfall with 8000/10000¢ promo tiers); 2 OCC concurrency_rules (expected_account_version + ERR_STALE_ACCOUNT_VERSION + HTTP 412 + 4 guarded operations); validation priority ordering stated in §3.12.
- Path purity (Contract 3): 431 backtick tokens, 0 path/method leakage in §3.

§2.2 emitted byte-verbatim. Neither SCAFFOLD_DIFFICULTY_DESIGN.yaml nor SCAFFOLD_CORNER_DESIGN.yaml read; no sibling tasks consulted.

## Step 5: Generate unit tests — 2026-06-10T04:28:25.000Z

Generated test infrastructure from the four input files plus unit-test-generator skill spec. Validated end-to-end against the task's reference impl under --isolation per-test-server: 66/66 pass.

test_helpers/ (9 files): __init__.py, types.py (13 entity TypedDicts; lean records ServiceAddress/ServicePlan/UsageRecord/AccountCredit omit updated_at/version), api_client.py, api_errors.py (22-error enum + HTTP map), assertions.py (+ net_credit_amount helper), factories.py (unique plan-code/serial sequences), constants.py, test_users.py (4 opaque-role headers + build_customer_headers), fixtures.py (composite setups across 5 tiers).

test_suite/ (conftest + 6 files, 66 tests): test_01_provisioning_lifecycle (12), test_02_scheduling (6), test_03_metering_billing (14), test_04_outages_credits (6), test_05_disconnect_transfer (13), test_06_validation_and_access (15).

Queue coverage: Queue A (Difficulty) 37 tests — all 18 difficulty instances covered ≥2 each. Queue B (Corner) 29 tests — all 29 non-stub corner instances covered ≥1. Every test carries exactly one verbatim Design: tag; 0 untagged/dual-tagged/dangling, 0 non-verbatim PRD citations.

Skipped/adjudicated: 7 corner stubs (excluded_because) correctly not translated, all 7 difficulty_instance cross-refs resolve. Lease-proration exact cents relaxed (PRD §3.7 "counting the start day" doesn't pin day-0/day-10 → 1450/950 vs 1500/1000; impl produced former) — 3 affected tests assert only uniquely-derivable facts (emission, source_id, positivity, net-zero conservation). Overage-estimate exact value relaxed (§3.10 "days elapsed" doesn't pin start-day count) — tests assert estimate≠FINAL, FINAL==2890, non-mutating read. One scaffold-vs-PRD conflict corrected: corner change_plan instance specified PENDING account but PRD §3.3 gates on ACTIVE; test activates first. PRD-pinned monetary literals (overage 5980/6000, bill 12327, outage credit 62, ETF 15000, promo tiers) asserted verbatim and pass.

## Step 6: Generate implementation — 2026-06-10T04:28:25.000Z

Generated Python + Flask implementation at workspace/implementation/ (24 files). All 61 PRD §4 endpoints (60 domain + /_clock/set_current_utc) implemented.

Files: start.sh (executable), requirements.txt (flask==3.0.3); app.py, db.py (in-memory dicts), errors.py, response.py, middleware.py (auth/RBAC), clock.py (logical test clock), timeutil.py (ISO 8601 ±3-digit); services/helpers.py, services/calculations.py (6 calc rules), services/domain.py (cascades + credit emission), services/serialize.py; 9 route blueprints (catalogs, equipment, accounts, service_orders, scheduling, billing, outages, transfers, clock_routes).

Response envelope meta/response_type/data; pagination limit/offset/total_count/has_more (default 10, min 1, max 100); 23 error IDs mapped to PRD §5 HTTP statuses. Parallel dimensions: Account status × service_state; BillingCycle billing_state × throttle_state (throttle flips when cumulative usage strictly > included_gb under THROTTLE policy). Cyclic equipment IN_INVENTORY→LEASED→RETURN_PENDING→RETURNED→IN_INVENTORY + LOST branch reversing LEASE_PRORATE credit to net 0. Cascades: activation (assign+lease, account→ACTIVE, open 30-day cycle); disconnect/transfer (ETF or TRANSFER_WAIVER, equipment→RETURN_PENDING + lease proration, cycle close→finalize). OCC on Account.version for 4 guarded writes, each bumping version by 1. Calculations use Decimal/ROUND_HALF_UP (no float). Validation priority order auth→forbidden→not_found→body→state→ownership→domain→OCC per §3.12. 4 lean entities carry id/created_at only; 9 versioned carry updated_at/version too.

start.sh reads $PORT (default 10000), binds 0.0.0.0, runs python3 app.py foreground via exec, guards pip install behind import check. In-memory only — no SQLite/JSON/disk/tmp, no module-level seeding, empty store (total_count=0) on fresh boot.

## Step 7: Test & fix loop — 2026-06-10T04:31:18.000Z

All 8 parallel rounds fully clean: 66 passed, 0 failed, 0 errors, 0 skipped in every round. No flakiness surfaced across the concurrent sweep. Task already in passing state — exited on the first iteration.

Iterations run: 1 (single 8-round parallel stability sweep). Union of failures across all 8 rounds is empty, so no diagnostic protocol (STEP 0–3) triggered.

Tests deleted: None. Fixes applied to test_helpers/: None. Fixes applied to implementation/: None.

Notes: implementation is a Flask app with in-memory module-level dict storage (db.py), no startup seeding, start.sh installs deps only when missing then exec python3 app.py — consistent with wipe-on-reboot and per-test-server isolation. 66 tests across 6 files all passed under --isolation per-test-server (server rebooted before every test), stable under ~8× concurrent load. Verified all 8 results.{1..8}.json: passed==total==66, failed==0.

## Step 8: Finalize PRD — SKIPPED — 2026-06-10T04:31:18.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 test_suite/ fixes, 0 test_helpers/ fixes, and 0 implementation/ fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits. No PRD_FINALIZED.md produced. Per orchestrator spec, the subagent was not spawned.

## Step 9: Complete PRD — 2026-06-10T04:38:40.000Z

Output: workspace/PRD_COMPLETED.md. Started from PRD.md (PRD_FINALIZED.md absent — Step 8 skipped). Source PRD.md (311 lines, 50,696 chars) → PRD_COMPLETED.md (311 lines, 53,427 chars); char delta +2,731; no line-count change (all in-paragraph inserts/revisions, no new sections).

11 changes total — 2 mismatch-revisions, 9 ambiguity-pins:
- §2.3 — insert — ambiguity — records with identical created_at ordered by id as stable secondary sort key — services/helpers.py:104
- §2.5 — revise — mismatch — removed change-plan from serviceability-gate scope: on plan change only the speed gate runs (impl never checks coverage_status on change-plan) — routes/accounts.py:90-94
- §3.2 (account create) — insert — ambiguity — Customer must supply customer_user_id == X-User-ID or get ERR_NOT_ACCOUNT_OWNER — routes/accounts.py:39-41
- §3.2 (ship-kit) — insert — ambiguity — ship-kit also runs §2.5 speed gate (after serviceability, before eligibility) — routes/service_orders.py:88-90
- §3.2 (ship-kit) — revise — mismatch — corrected "Shipping reserves an equipment unit" to "shipping assigns/holds no unit; kit ships even with empty inventory; equipment selected only at activation" — routes/service_orders.py:72-96
- §3.2 (activate) — insert — ambiguity — selected IN_INVENTORY unit is oldest by created_at when several exist — routes/service_orders.py:201-207
- §3.2 (cancel) — revise — mismatch (consequence) — corrected cancel-KIT_SHIPPED to "no equipment side effect, since shipping never reserved a unit" — routes/service_orders.py:174-181
- §3.5 (restore-speed) — insert — ambiguity — pinned ERR_INVALID_STATE precondition (OPEN, THROTTLED cycle) and updated billing-cycle object response — routes/accounts.py:135-149
- §3.6 (issue-credit) — insert — ambiguity — issue-credit returns 200 OK with now-CREDITED outage event (not the emitted credit) — routes/outages.py:131-134
- §3.10 (billing cycles) — insert — ambiguity — account may hold multiple OPEN cycles; "the open cycle" resolves to most-recently-created OPEN cycle — services/domain.py:48-56
- §3.10 (overage-estimate) — insert — ambiguity — as_of_iso default (current clock), usage-so-far/days-elapsed defs (counting start day), non-mutating response (cycle object with overage_charge_cents carrying estimate, billing_state stays OPEN) — routes/billing.py:69-109, services/calculations.py:57-67
- §3.11 (goodwill credit) — insert — ambiguity — issuing goodwill credit returns 201 Created with new AccountCredit object — routes/accounts.py:168-177
- §3.12 (clock) — insert — ambiguity — created_at/updated_at read pinned clock; response api_request_timestamp uses real wall-clock; /_clock/set_current_utc returns 200 OK with empty object — db.py:42-43, response.py:27-31, routes/clock_routes.py:24

Key findings: substantive mismatch is self-install kit reservation (PRD claimed shipping "reserves an equipment unit" but impl reserves nothing at ship time — kit ships with zero inventory, fails only at activation with ERR_NO_EQUIPMENT_AVAILABLE; propagated to cancel-KIT_SHIPPED prose). Second mismatch: §2.5 claimed change-plan runs both gates, impl runs only the speed gate. Other changes fill silences on response shapes/status codes, defaults, ordering, multi-OPEN-cycle resolution.

## Pipeline complete

All 9 steps executed end-to-end. Final state: 13-entity Expert-band scaffold, 311-line PRD, 66-test suite (Queue A 37 / Queue B 29), Flask in-memory implementation passing 66/66 across all 8 parallel stability rounds. Step 8 skipped (zero Step 7 changes). PRD_COMPLETED.md produced with 11 ambiguity/mismatch pins.
