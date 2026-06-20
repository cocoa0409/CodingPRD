# Worklog — task_0395_community_solar_subscription

Scenario: Community Solar Subscription: project/garden capacity & subscriber share, allocation & bill-credit calculation, monthly savings reconciliation (utility on-bill), waitlist & churn/transfer, true-up & overproduction, enrollment & cancellation, low-income carve-out, REC tracking

Difficulty band: Expert (§0.4)

## Step 1: Create Task Directory — 2026-06-18T00:00:00.000Z

Task directory pre-allocated by parent orchestrator (auto-naming skipped per orchestration directive). Path: tasks/task_0395_community_solar_subscription with workspace/ already present.

## Step 2: Generate Scaffold — 2026-06-18T08:55:00.000Z

Generated in two parts due to a mid-response connection drop on the first scaffold-generator subagent (it had already written a complete, valid SCAFFOLD.yaml). A second fresh subagent generated only the two missing design-index companion files, reading the existing SCAFFOLD.yaml for full consistency.

SCAFFOLD.yaml (Expert band): 10 entities, 44 endpoints, 5 state machines, 6 calculations, 24 errors, 3 roles. All 13 top-level sections present; valid YAML; neither design key leaked into it.

Design-index files (second subagent, verbatim summary):

All validations pass. Both files are complete and consistent.

Generated the two missing design-index companion files for task_0395_community_solar_subscription, fully consistent with the existing SCAFFOLD.yaml (10 entities, 44 endpoints, 5 state machines, 6 calculations, 24 errors, 3 roles).

SCAFFOLD_DIFFICULTY_DESIGN.yaml (single top-level key scaffold_difficulty_design): 18 difficulty instances — all 9 §0.5 Difficulty Rules × 2 instances each, each honoring its differentiation clause:
- dual_variant_calc: bill-credit provisional-vs-final (Allocation domain) + churn-risk snapshot-vs-trailing (Subscriber domain)
- combinatorial_formula: tiered program fee (mode a, multi-input non-linear) + true-up overproduction (mode c, pinned eval order)
- non_linear_state_machine: Subscription suspend/resume cycle + Reconciliation parallel credit×dispute dimensions
- transitive_cascade: reconcile depth-3 (period→allocation→reconciliation→REC) + cancel depth-2 (release→waitlist auto-promotion)
- priority_pair_validation_conflict: business_fiscal-vs-business_constraint + state-vs-business_safety
- boundary_precision_check: tier boundary gross 5000/5001 (fee metric) + REC floor zero-count at 999/1000 (count metric)
- cross_entity_state_dependency: period-close-blocked-by-disputed-reconciliation + transfer-blocked-by-jurisdiction
- resource_temporal_overlap: duplicate period_month (per-project bucket) + duplicate utility_account_no (global namespace)
- compensating_invariant: transfer conserves committed_kw + reopen/reconcile conserves rec_minted_total

SCAFFOLD_CORNER_DESIGN.yaml (single top-level key scaffold_corner_design): 47 corner instances — 40 active test recipes + 7 excluded_because stubs — spanning all nine claim-extraction-guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model).

Consistency confirmation: Every rule_id, entity, field, state, error code, calculation, endpoint, and role referenced in both files traces verbatim to the existing SCAFFOLD.yaml. Verified by: (1) scaffold_lint.py → VERDICT: clean lint (408 calls scanned, all conform to §1.5; all FKs reverse-reachable; OCC version fields use ${var} references); (2) YAML parses with exactly one required top-level key each; (3) all excluded_because.difficulty_instance references resolve to real §1.8 instance names; (4) no name collisions across the union; (5) all formula-derived asserts pre-computed as exact literals (fees 900/450/500, net 9100/9550, rollover 500/2000, RECs 10/0, churn 50). Neither design key leaked into SCAFFOLD.yaml.

One note: ERR_IMMUTABLE_RESOURCE is the sole error in the catalog not reachable through any declared §1.5 endpoint (CarveOutAdjustment has no transition/update endpoint), documented inline as a comment rather than fabricating an untriggerable test.

## Step 3: Copy Shared Files — 2026-06-18T08:56:00.000Z

Copied ./INSTRUCTION.md → workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-06-18T09:05:00.000Z

PRD.md written (270 lines, 43976 bytes). Verbatim subagent summary:

All Contract-2 high-risk categories are fully and precisely expressed. Both OCC rules name the write endpoint (via state-transition framing), the occ field, the version-mismatch rejection, and the exact error ID + HTTP status. The carve-out gate covers both approve and activate; the capacity gate covers submit, resubmit, and activate. The allocation waterfall's pinned order, the tiered fee, the churn snapshot/trailing variants, the true-up circular-order sweep, and REC minting are all reconstructible step-for-step without pseudocode or fuzzy words. The PRD is complete and all three Hard Contracts pass.

Size: 270 lines. 5 top-level sections (§1 Introduction, §2 Global Specifications with 9 subsections, §3 Business Logic with 13 subsections, §4 Endpoint Definitions, §5 Error Catalogue). §4 table 4 columns; §5 table 2 columns.

Zero-Silence coverage confirmed:
- Entities (10/10): SolarProject, Subscriber, Enrollment, Subscription, WaitlistEntry, BillingPeriod, Allocation, Reconciliation, RECBatch, append-only CarveOutAdjustment (common_fields: false — only id/created_at, guarded by ERR_IMMUTABLE_RESOURCE).
- State machines (5/5): Enrollment (cyclic reject→resubmit), Subscription (suspend↔resume, transfer loop, cancel), BillingPeriod (compound + reopen cycle), Reconciliation (parallel credit_status × dispute_status), RECBatch (fork-join RETIRED/TRANSFERRED with divergent ledger side-effects).
- Calculations (6/6): allocation waterfall (pinned floor-then-remainder by descending fractional part, tie-break created_at asc), provisional vs final bill credit, tiered savings reconciliation (carve-out rate 0.05, tiers 5000/20000 cents, multipliers 1.00/0.90/0.80, round-half-up), churn risk (snapshot 40/35/10 + trailing +50 over last 3 CLOSED periods, cap 100), true-up overproduction (cap = min(2000, ceil(committed_kw × 50)), rollover/forfeit/credit in pinned order), REC minting (floor of metered/1000).
- Validations (19/19): priority ordering in §2.9; every check matched to error_id; applies_to scopes enumerated.
- OCC (2/2): transfer→expected_project_version→ERR_STALE_PROJECT_VERSION (412); meter + reconcile→expected_period_version→ERR_STALE_PERIOD_VERSION (412).
- Endpoints (44/44): exact method+path coverage verified by diff (scaffold's "32 endpoints" comment was a stale label; actual count 44).
- Errors (24/24): every ID appears in §2/§3 prose with trigger condition + §5 status table.
- Roles (3/3): GridOperator, ProgramAdmin, Subscriber.

Hard Contracts — all PASS (field coverage 68/68; rule coverage 19 validations + 2 OCC + 5 state machines + 6 calculations; path-purity 0 path tokens in §3). Neither design-index file read; no sibling tasks accessed.

## Step 5: Generate Unit Tests — 2026-06-18T09:25:00.000Z

Verbatim subagent summary:

The paste count failed on syntax but the per-file numbers sum to 13+11+16+10+24 = 74, matching the pytest collection. All complete.

Generated complete test infrastructure for task_0395_community_solar_subscription from the four inputs plus the unit-test-generator skill spec.

Test files: 5 (in test_suite/)
- test_01_resource_lifecycle.py (13 tests) — entity creation/retrieval/defaults/computed/system fields, FK integrity, append-only immutability, listing/pagination, immediate consistency
- test_02_state_machines.py (11) — enrollment loop, subscription suspend/resume cycle, parallel reconciliation dimensions, period epoch, REC fork-join
- test_03_calculations.py (16) — bill-credit dual variant, churn snapshot, tiered fee, true-up overproduction, REC floor, allocation waterfall
- test_04_cascades_and_invariants.py (10) — reconcile depth-3 cascade, cancel→waitlist auto-promotion, transfer/reopen conservation invariants, derived-field reconciliation
- test_05_validations_and_errors.py (24) — cross-entity state gates, duplicate-resource guards, business validations, OCC, RBAC

Total tests: 74 — 34 trace to queue A (§1.8 Difficulty), 40 trace to queue B (§1.9 Corner).

Coverage: All 17 emitted difficulty instances have ≥2 tests each; all 40 non-stub corner instances have ≥1 test (0 gaps). All 7 excluded_because: corner stubs correctly NOT translated; all 7 stub→difficulty cross-references resolve to real instances.

SKIPPED design instances: 1 (under PRD-first filter)
- error-precedence / non-unique-derivability (1): Difficulty/priority_pair_validation_conflict/full_gate_business_constraint_beats_capacity_business_fiscal — asserts ERR_CAPACITY_EXCEEDED pre-empts ERR_PROJECT_FULL, but PRD §2.9 puts both in the unordered final "operation-specific business rules" bucket and §3.3 prose lists the FULL gate first; a faithful PRD-only implementer could surface ERR_PROJECT_FULL, so the outcome is not uniquely derivable. Its corner stub priority_capacity_beats_full_corner points at this skipped instance and is correctly not translated either.

Validation passed: all 74 tests collect cleanly under pytest; all 101 PRD citation quotes survive a literal grep of PRD.md (C1); every test carries exactly one Design: line (C4); no skip/xfail/skipif markers; all helper and suite files byte-compile and import against the framework.

test_helpers/ files created (9): __init__.py, types.py, api_client.py, api_errors.py, assertions.py, factories.py, constants.py, test_users.py, fixtures.py

(Append-only CarveOutAdjustment modeled with id+created_at only — no version/updated_at — per PRD §2.4; Subscriber is entity_backed, so all ownership-gated subscriber calls thread the real subscriber id via make_subscriber_headers().)

## Step 6: Generate Implementation — 2026-06-18T09:25:00.000Z

Verbatim subagent summary:

Implementation complete.

Files under implementation/:
- start.sh — bash launcher (executable)
- requirements.txt — Flask==3.0.3
- app.py — Flask entry point: all 44 routes, error handlers, validation pipeline, state machines, cascades
- services.py — ledger recomputation, allocation waterfall, all 6 calculations, churn risk, serializers
- db.py — in-memory store (one dict per entity, keyed by id)
- errors.py — ApiError + the 24-error catalogue with HTTP statuses
- response.py — standard meta/response_type/data envelope, ISO-8601 UTC 3-digit timestamps, req_ request ids
- validation.py — body field validation + pagination (limit/offset)
- auth.py — X-User-ID/X-User-Role extraction, RBAC roles

Flask app entrypoint: app.py (app = Flask(__name__)); run via python3 app.py with app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True).

start.sh contract: reads $PORT (default 10000), binds 0.0.0.0, runs the server in the foreground via exec python3 app.py. pip install guarded on python3 -c "import flask" so per-test reboots don't re-run it. Verified booting via bash start.sh — server responds within ~2s.

Storage: in-memory only — module-level Store with plain dicts. No SQLite, no JSON dump, no /tmp cache. No startup seeding; store empty on every boot and confirmed empty after a start.sh restart. Every entity created by tests via declared endpoints.

Endpoints implemented: 44 distinct method/path routes covering every row of the PRD §4 endpoint table.

Verified behaviors via live smoke tests: full enrollment→activation→period→meter→reconcile→issue→apply→true-up→close lifecycle; allocation waterfall floor+remainder; tiered program fee incl. 5000-cent boundary; carve-out 3-decimal rounding; REC minting floor(metered/1000) and divergent retire vs transfer ledger effects; true-up cap min(2000, ceil(committed_kw×50)); OCC stale-version 412s on transfer and meter; validation ordering (401→403→404→400→422); dispute/close/reopen gates; subscriber ownership enforcement (403); append-only carve-out adjustment; waitlist auto-promotion on cancel; lifetime/net-savings ledger sync on apply.

## Step 7: Run Tests and Iterate — 2026-06-18T09:40:00.000Z

Verbatim Step 7 subagent summary:

Iterations run: 2 (initial sweep → 1 deletion → confirming sweep).

Initial state: The first 8-round sweep was deterministic — exactly one test failed in all 8 rounds: test_occ_stale_period_version_on_meter_returns_412 (73/74 passing). No flakiness; the failure was a hard error-precedence contradiction.

Tests deleted (1):
- test_occ_stale_period_version_on_meter_returns_412 (test_suite/test_05_validations_and_errors.py) — ERROR PRECEDENCE SILENCE / unique-derivability collapse (STEP 1b).
  - The test does a first meter write (OPEN → METERED, which bumps the period version), then issues a second meter write carrying the now-stale version and asserts ERR_STALE_PERIOD_VERSION (412).
  - PRD §2.8 (line 100) covers stale-version → 412 in isolation, but PRD §2.8's precedence sentence (line 104) fixes the order: "Eighth, state validity... else ERR_INVALID_STATE. Ninth, the optimistic-concurrency version check, else the relevant stale-version error." State validity is checked before the OCC version check.
  - Metering is defined only as OPEN → METERED (PRD line 164), and a period's version can advance only by leaving OPEN. So any stale-version meter request is necessarily also a non-OPEN (state-invalid) request, and the priority-8 check wins → ERR_INVALID_STATE. ERR_STALE_PERIOD_VERSION is strictly unreachable for the meter endpoint. A faithful PRD-only implementer correctly returns ERR_INVALID_STATE. Because PRD does not support an "ERR_STALE_PERIOD_VERSION is possible" reading for this path, relaxation to validate_error_is_one_of([...]) was not justified — deletion is required. Scaffold rule that drove this test: Corner/cross_cutting_complexity_layers/occ_stale_period_version_on_meter_returns_412.

Fixes applied to test_helpers/: none.
Fixes applied to implementation/: none. The implementation's meter handler (app.py lines 766–771) already evaluates state validity before the OCC check, exactly matching the PRD precedence — it was PRD-faithful throughout.

Final pass count: 73/73 passing, identical across all 8 parallel rounds (0 failures each round).

ORCHESTRATOR NOTE: The subagent's final result.{1..8}.json files were not on disk afterward (its sweep cleaned them up). Orchestrator re-ran an independent authoritative 8-round parallel sweep to regenerate the result files and confirm — all 8 rounds passed 73/73 (results.1.json..results.8.json now persisted under workspace/implementation/). Suite test count confirmed 73 (test_05: 24→23, the single deletion).

## Step 8: Finalize PRD — 2026-06-18T09:45:00.000Z

Step 8 ran (not skipped: Step 7 had 1 deletion, so the all-zero skip condition was not met). Verbatim subagent summary:

PRD_FINALIZED.md is byte-identical to PRD.md (270 lines each, cmp confirms identical). Zero edits — the correct outcome.

PRD.md vs PRD_FINALIZED.md: 270 lines vs 270 lines, 0% delta — byte-identical (zero edits). Verified with both diff and cmp.

Changes: None. The single Step 7 item is a pure test deletion with no PRD silence and no PRD/impl mismatch, so no patch is warranted.

Per-edit pre-edit search log (for the one diff item evaluated):
- (a) Subject: Whether the meter endpoint's error precedence — state-validity (ERR_INVALID_STATE) vs OCC version check (ERR_STALE_PERIOD_VERSION) — is a PRD silence/mismatch the impl pinned, or already uniquely determined by PRD.
- (b) Impl paths enumerated/read: app.py:749-783 (meter_period — state check before OCC, lines 767-768 then 770-771); app.py:786-800 (reconcile_period parallel OCC endpoint — same ordering, §2.9); db.py:48-51 (touch bumps version on every mutation); all period-touch callsites (app.py 782, 848, 863, 894, 909 — every one leaves OPEN or operates on already non-OPEN; line 171 touch is on a project not a period); app.py:664-727 (open_period — period born at version 1, forecast waterfall doesn't touch period so version stays 1 while OPEN). Confirms a period's version advances only by leaving OPEN, so ERR_STALE_PERIOD_VERSION is genuinely unreachable on /periods/{id}/meter. test_05 confirmed the deleted test is gone.
- (c) Wording adjustment: None. PRD §2.9 (line 104) already states the precedence unconditionally; §2.8 (line 100) defines the meter OCC guard; impl matches §2.9 exactly. No PRD-silence and no PRD/impl divergence → PRD_FINALIZED.md left byte-identical.

Orchestrator confirmed: PRD_FINALIZED.md exists (43976 bytes), cmp PRD.md PRD_FINALIZED.md → byte-identical.

## Step 9: Complete PRD — 2026-06-18T09:50:00.000Z

Full PRD-vs-implementation completeness scan (always runs). Started from PRD_FINALIZED.md. Verbatim subagent summary:

Source vs completed:
- PRD_FINALIZED.md: 270 lines, 43,976 chars
- PRD_COMPLETED.md: 270 lines, 45,669 chars
- Char delta: +1,693 (no line-count change — all edits in-paragraph)

Counts: 8 changes total — 5 ambiguity-pins, 3 mismatch-revisions.

Per-change log:
- §2.1 (RBAC ownership) — insert — ambiguity — failed resource-ownership check returns ERR_FORBIDDEN, runs after path/referential existence but before required-field/range/state/business checks — app.py:253,303,479,567,604,653,1024.
- §2.3 (Pagination/ordering) — revise — ambiguity — non-integer limit/offset is also ERR_PAGINATION_INVALID; equal-created_at records tie-break by creation/insertion sequence — validation.py:69-81,87.
- §3.2 (Subscriber registration) — revise — mismatch — annual_usage_kwh must be an integer (require_int → ERR_INVALID_REQUEST) — app.py:195.
- §3.2 (Trailing churn variant) — insert — ambiguity — trailing +50 applies only when a CANCELLED subscription's cancellation_effective_period_id is itself CLOSED and among the three highest-sequence_index CLOSED periods of that period's project — services.py:144-170.
- §3.5 (Transfer → cancellation period) — insert — ambiguity — when multiple OPEN periods exist, greatest-sequence_index one is used as cancellation_effective_period_id — app.py:462-471,520.
- §3.6 (Waitlist queue) — insert — ambiguity — requested_share_kw must be > 0 (ERR_VALIDATION); queuing imposes no FULL/capacity/carve-out gate — app.py:596-607.
- §3.7 (Open period) — revise — mismatch — forecast_production_kwh must be an integer (require_int) — app.py:674.
- §3.8 (Provisional credit) — revise — mismatch — provisional_credit_cents computed once from forecast basis at OPEN, NOT recomputed at metering (metering updates only allocated_kwh) — app.py:726-727,776-781.
- §3.9 (Metering) — revise — ambiguity — metered_production_kwh must be an integer; missing, non-integer, or negative all raise ERR_METER_READING_REQUIRED — app.py:756-760.

Verified-no-change-needed spot checks: committed_kw including TRANSFERRING (§2.5); true-up cap/rollover order (§2.7/§3.12); tiered fee tiers & carve-out 0.05 rate (§3.10); REC floor & always-mint-batch (§3.10); resubmit re-checking only FULL+capacity not usage cap (§3.3); waterfall remainder tie-break two declared keys (§3.7); abstract ERR_IMMUTABLE_RESOURCE (§2.4 — no impl route triggers it, nothing concrete to pin).

Orchestrator confirmed: PRD_COMPLETED.md exists (45669 bytes; 271 lines incl. trailing newline; +1683 chars over PRD_FINALIZED.md). Steps 8/9 touched only PRD docs — all 8 stability-sweep result files still read 73/73 (implementation/ and tests untouched).

## PIPELINE COMPLETE — 2026-06-18T09:50:00.000Z

Final state: 8/8 stability-sweep rounds PASS at 73/73. All deliverables present:
SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml,
worklog.md, test_helpers/ (9 files), test_suite/ (5 files, 73 tests),
workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (+ results.1..8.json)}.
