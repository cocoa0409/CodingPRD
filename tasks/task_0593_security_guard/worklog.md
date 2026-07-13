# Worklog — task_0593_security_guard

Scenario: 593. Security Guard Services (Allied Universal style): post/site & coverage schedule, guard licensing & assignment, shift clock-in & tour/checkpoint (NFC), incident report & escalation, bill-rate vs pay-rate margin, overtime & relief/no-show, client invoice & post orders, training/cert tracking

Difficulty: Expert (passed to Step 2 scaffold-generator only).

## Step 1: Create task directory — 2026-07-11T13:56:30.000Z

Task directory pre-created and reserved by the operator: `./tasks/task_0593_security_guard` (with `workspace/` inside). Index-scanning skipped per instruction; no directory created or renamed.

## Step 2: Generate scaffold — 2026-07-11T13:56:30.000Z

All three scaffold artifacts are generated and pass the linter clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_0593_security_guard/SCAFFOLD.yaml
  Difficulty design:  tasks/task_0593_security_guard/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_0593_security_guard/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    42
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  931

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## What was generated

**Files** (all under `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0593_security_guard/`): `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`.

**Complexity profile** — Expert. Primary archetype `temporal_windowing` + secondary `ledger_reconciliation`; layers: optimistic concurrency, cascading side effects, dual-variant calculation, version-pinning-on-approval. Topology **flat** (FK peers, no nested URLs), state-machine shape **cyclic**, role model **segregation_of_duties**, consistency **immediate**. Self-referential FK via `CoverageShift.relief_for_shift_id`.

**Entities (11)**: Client, Site, Post, PostOrder, Guard, Credential, CoverageShift, TourScan, IncidentReport, Invoice, InvoiceLine. (NFC checkpoints are an ordered `Post.checkpoint_tag_uids` array rather than a separate table, keeping the surface dense.)

**State machines (5)**: CoverageShift (cyclic — NO_SHOW/OPEN_UNFILLED/re-crew loop, 8 states), Guard (**parallel dimensions**: `employment_status` × `license_status`, with a LICENSED→EXPIRED→LICENSED cycle), IncidentReport (branching + two cycles: review↔escalate and review→info_requested→submit), Invoice (cyclic ISSUED→DISPUTED→ADJUSTED→ISSUED), PostOrder (linear, supersede-on-publish).

**Concurrency (§1.2.1)**: 2 OCC rules — `shift-assign-stale-shift` (`expected_shift_version` on `POST /shifts/{id}/assignments`, CREATE-with-supersede reassignment) and `post-order-create-stale-post` (`expected_post_version` on `POST /post-orders`). Both 412 `ERR_STALE_VERSION`.

**Calculations (10)**: `shift_billable_amount` (dual-variant PROVISIONAL vs FINAL: quarter-hour **ceiling**, overrun cap, 10% SLA credit), `guard_weekly_pay` (chronological weekly accumulator, quarter-hour **half-up**, 40h OT split, night differential — combinatorial mode **(a)**), `invoice_total` (tiered admin fee keyed on **subtotal, not total** — combinatorial mode **(c)**; a credit crossing a tier boundary *raises* the fee while lowering the total), `guard_reliability_score` (dual-variant PROVISIONAL vs CONFIRMED on the Guard risk domain), `tour_compliance`, `client_balances`, `guard_committed_hours`, `site_coverage_status`, `guard_license_status`, `shift_scheduled_hours`.

**Endpoints (42)** — 33 business + 9 single-resource reads required by the linter's FK reverse-reachability check; one test-driving endpoint `POST /_clock/set_current_utc` with the mandated `2026-05-01T00:00:00Z` startup default, plus a business `POST /compliance-sweeps` for licence expiry.

**Error catalog: 30 codes**. **Roles: 6** — AccountManager, Scheduler, Guard (`entity_backed:Guard`), FieldSupervisor, ComplianceOfficer, PlatformAdmin (all others `opaque`).

**§1.8 difficulty design**: 9 rule_ids × **2 instances = 18**, all with fully-executable `setup_api_calls` chains and literal asserts computed by running the formulas (e.g. provisional 33750 vs final 31387; night-OT shift pay 24200 / weekly 103400; admin fee 9000→11200 while total 189000→151200; exactly-40.00h week → 0.00 OT, 88000 cents).

**§1.9 corner design**: **45 instances** across all 9 guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model), of which **3 are `excluded_because:` stubs** pointing at §1.8 instances.

Key design pins worth knowing: billing ceils to the quarter hour while pay rounds half-up (deliberate divergence); licence expiry is *swept*, never lazily evaluated on read; release cascades only touch shifts starting at/after the logical clock; and the admin-fee tier is non-monotonic by construction.

## Step 3: Copy shared files — 2026-07-11T13:56:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0593_security_guard/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-07-11T14:05:00.000Z

All three hard contracts pass. The PRD is written.

**Output:** `/Users/uni/Desktop/吉/project/custom_prd_bench/tasks/task_0593_security_guard/workspace/PRD.md` — 408 lines.

## Structure

**§1 Introduction** (3 paragraphs) — framed from business pain (margin erosion, licence lapse, no-shows), then the two design commitments: the logical clock and swept-not-inferred expiry.

**§2 Global Specifications** — 10 subsections, domain-derived titles:
2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim) · 2.3 Pagination · 2.4 The Logical Clock · 2.5 Common Resource Properties · 2.6 Version Pinning and Optimistic Concurrency Control · 2.7 Money, Hours and Rounding Discipline · 2.8 Request Validation Order · 2.9 Cascade Discipline and Derived-Field Freshness · 2.10 Segregation of Duties

**§3 Business Logic** — 9 subsections grouped by lifecycle/aggregate:
3.1 Clients, Sites and Guard Posts · 3.2 Post Orders and the Briefing Pin · 3.3 The Guard Record: Two Dimensions, Licences and Certifications · 3.4 Building the Coverage Schedule · 3.5 Assignment, Reassignment and Confirmation · 3.6 On Duty: Clock-In, the NFC Tour, and Clock-Out · 3.7 No-Shows, Reliability and Automatic Suspension · 3.8 Incident Reporting, Escalation and Closure · 3.9 Invoicing the Client

**§4** 41-row endpoint table (4 columns). **§5** 30-row error table (2 columns).

## Coverage

- **Entities:** 11 (Client, Site, Post, PostOrder, Guard, Credential, CoverageShift, TourScan, IncidentReport, Invoice, InvoiceLine). TourScan's `common_fields: false` stated explicitly (no `updated_at`, no `version`).
- **State machines:** 5 — CoverageShift (14 transitions, cyclic incl. `NO_SHOW → OPEN_UNFILLED` and `SCHEDULED → SCHEDULED` reassignment), Guard (parallel: 4 employment + 4 licensing transitions incl. the `LICENSED → EXPIRED → LICENSED` cycle), IncidentReport (9, incl. both cycle edges), Invoice (9, incl. `ISSUED → DISPUTED → ADJUSTED → ISSUED`), PostOrder (2).
- **Calculations:** all 9 rendered as prose with no operator syntax — `shift_scheduled_hours`, `shift_billable_amount` (both PROVISIONAL and FINAL variants, quarter-hour ceil, 0.5h overrun cap, 10% SLA credit), `guard_weekly_pay` (chronological ISO-week sweep, 40.00h threshold, 1.5× OT, 1.10× night differential on hours 22–05 UTC, rate rounded before multiplication), `guard_reliability_score` (both variants, 30/5/2 penalties, strict `< 50` suspension gate), `tour_compliance` (empty-tour = 100.0 convention), `invoice_total` (descending 8.0/5.0/3.0 tiers keyed on subtotal, with the credit-raises-fee consequence stated), `client_balances`, `guard_committed_hours`, `site_coverage_status` (48h window).
- **OCC:** both `concurrency_rules` entries — `expected_shift_version` on assignment and `expected_post_version` on post-order create — with `ERR_STALE_VERSION`/412, framed purely as stale-version rejection.
- **Endpoints:** all 41. **Errors:** all 30. **Roles:** all 6, each `identity:` translated (Guard = entity-backed; other five = opaque).

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 80 required, 80 present, 0 missing
- endpoints[].request_body/input: 45 required, 45 present, 0 missing
- endpoints[].output keys: 12 required, 12 present, 0 missing
- endpoints[].query_params: covered within the 45 (limit, offset, status, kind, *_id filters)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (§2.8 states the full ordered pipeline), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 38 checked, 38 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 41 checked, 41 expressed, 0 missing
- entities[].fields[] structured content: 80 checked, 80 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (UNASSIGN×3, CANCEL×3, NO_SHOW×2, VOID×4, RESOLVE×2, ISSUE×2), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 622
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Note: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.
