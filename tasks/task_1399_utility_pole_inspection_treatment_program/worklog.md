# Worklog — task_1399_utility_pole_inspection_treatment_program

## Step 1: Create task directory — 2026-08-13T00:00:00.000Z

Task directory `tasks/task_1399_utility_pole_inspection_treatment_program/` and its `workspace/` subdirectory were pre-created and pre-assigned (Step 1 DONE per invocation instructions). No index scan performed; no other task directory touched.

## Step 2: Generate scaffold — 2026-08-13T04:27:00.000Z

Done. All three scaffold artifacts generated at `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/` and `scaffold_lint.py` reports **VERDICT: clean lint** (40 endpoints, 10 entities, 24 difficulty + 47 corner instances, 483 calls scanned, zero violations). No sibling task directory was read at any point.

## What was generated

**SCAFFOLD.yaml** (§1.0–§1.7)
- **Profile**: workflow_orchestration + compliance_audit; layers = optimistic_concurrency, dual_variant_calculation, ops_run_checkpoint, cascading_side_effects; flat topology, cyclic state shape, **segregation_of_duties** role model (QAReviewer can't review own submissions; Contractor = entity_backed by ContractorCrew with ownership checks), immediate consistency.
- **10 entities**: ProgramBudget, InspectionCycle, Pole, InspectionTask, TreatmentWorkOrder, WarrantyClaim, ContractorCrew, ReplacementWorkOrder, AttachmentAudit, BacklogSnapshot (append-only, `common_fields: false`).
- **8 state machines**, three+ non-linear: InspectionTask rework cycle (OPEN→SUBMITTED→REJECTED→OPEN, ESCALATED at rework_count 2), TreatmentWorkOrder retreat cycle (FAILED_QA→SCHEDULED re-baselines warranty), ReplacementWorkOrder QUEUED↔DEFERRED cycle with auto-requeue at reconcile, AttachmentAudit **parallel dimensions** (audit_status × violation_status evolve independently).
- **9 calculations**, all literals machine-verified: dual-variant remaining strength (conservative 54.00 vs statistical 73.40 on identical readings), threshold classification (inclusive bounds, 60.00 → SERVICEABLE), NULL-first sampling selector with floor+min-1 sizing, non-linear priority score (FEEDER_CRITICAL floor 80, cap 100), compounding deferral escalation (1.08^n), waterfall funding with pinned snapshot-then-walk-skip-not-stop order, per-line-then-sum billing rounding (99434 literal; 1-cent divergence from sum-first), dual-variant crew quality score (lifetime 66.67 vs rolling 60.00), warranty window projection with retreat re-baseline.
- **2 OCC concurrency rules** (fund on ProgramBudget.version, GIS patch on Pole.version), 24 prioritized validations (auth → role → schema → existence → state → OCC → safety/SoD → constraint → temporal → referential → fiscal), 35 error codes, 5 roles.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml** — 24 instances (rules 2,3,4,5,6,7 carry 3 each; 1,8,9 carry 2), each with fully structured `setup_api_calls` replayed from empty-DB against the scaffold's own rules. Notable chains: depth-3 cascade (qa-accept REJECT_PRIORITY → Pole PRIORITY_REJECT → auto ReplacementWorkOrder → cycle.pending_replacement_count), depth-2 crew-suspension cascade, three distinct validation-priority pairs (state>fiscal, existence>state, safety>referential), half-open crew windows vs closed pole windows, fund/defund budget-cents invariant, sample/waive eligibility-pool invariant.

**SCAFFOLD_CORNER_DESIGN.yaml** — 36 full corner instances across all nine guide sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, complexity_layers, consistency_model) plus 11 `excluded_because` stubs cross-referencing difficulty instances. Covers terminal lockdowns, 404 FK/path existence for every resource, pagination envelope, immutability of snapshots, RBAC denials including entity-backed crew ownership, OCC stale-version negatives with `${var}` expressions, and clock-driven temporal corners (warranty expiry two-sided at exactly end-date vs +1 day; cure-deadline escalation at reconcile).

Notable design decisions: logical clock endpoint with mandatory default `2026-08-01T00:00:00Z`; budget↔cycle coupling via unique fiscal_year instead of an FK (avoids a reverse-reachability endpoint); attachments modeled as declared-vs-found counts on Pole/AttachmentAudit rather than a separate Attachment entity to keep density in the audit machinery; photo evidence as a typed array input on submit with classification-dependent referential validation.

## Step 3: Copy shared files — 2026-08-13T04:28:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1399_utility_pole_inspection_treatment_program/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T04:40:00.000Z

All checks pass. The PRD is complete.

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/workspace/PRD.md` — 7,277 words, from `SCAFFOLD.yaml` only (the two difficulty/corner design files were never opened).

### Structure
- **§1 Introduction** — 2 paragraphs (program context, then the operating loop the API manages).
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (5 roles with exact spellings, identity translation — `Contractor` entity-backed via `ContractorCrew.id`, the other four opaque), 2.2 response envelope (byte-identical to the fixed `section-2.2-response-structure.md`, verified programmatically), 2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields, plus list-filter parameters), 2.4 common resource properties (incl. the `BacklogSnapshot` exception — `id` + `created_at` only, no `updated_at`/`version`), 2.5 the logical clock (startup default `2026-08-01T00:00:00Z`, never wall-clock), 2.6 units/precision (integer cents, half-up, 2dp strengths/scores), 2.7 OCC (both rules with exact `expected_*_version` fields, error ids, HTTP 412), 2.8 the 11-stage ordered validation pipeline with explicit masking semantics, 2.9 left-to-right identifier resolution with all nine resource-specific 404s, 2.10 cascades and compensating actions.
- **§3 Business Logic** — 9 subsections organized by lifecycle: foundations (budgets/poles/cycle setup) → cycle opening & sampling → field submission with both strength variants and classification thresholds → QA review/rework/pole cascades → treatment lifecycle & contractor quality standing → warranty claims → attachment audits (parallel state dimensions) → replacement queue (priority score, escalation, fund/defund/defer/complete) → reconcile checkpoint (5-step order, waterfall, per-line-rounded production billing, snapshot). All 9 calculations rendered as precise prose (constants embedded: 250,000-cent default estimate, 1.08 deferral escalation, 45-day cure window, 120-day season, 40,000-cent mobilization, base rates/species multipliers, 70.00 suspension / 90.00 bonus thresholds, product warranty years) with no pseudocode or fuzzy wording.
- **§4 Endpoint table** — all 32 endpoints, 4 columns only, with a 201-vs-200 status paragraph.
- **§5 Error catalogue** — all 35 error ids, 2 columns only, no trigger conditions.

### Hard-contract audit results (all PASS)
```
Field coverage check:
- entities[].fields: 96 required, 96 present, 0 missing
- endpoints[].request_body: 53 required, 53 present, 0 missing
- endpoints[].query_params: 9 required, 9 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority: 24 checks across 11 priority tiers, all expressed in the ordered §2.8 pipeline + workflow prose, 0 missing
- concurrency_rules[] OCC: 2 checked, 2 expressed (write capability + expected field + error id + 412), 0 missing
- state_machines[].transitions: 31 checked (incl. both AttachmentAudit dimensions), 31 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 24 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed (incl. ERR_POLE_REPLACED's 4 endpoint scopes), 0 missing
- entities[].fields[] structured content (defaults, enums, computed derivations): reconstructible from prose, 0 missing
- sibling-branch symmetry: 7 groups (CONSERVATIVE/STATISTICAL, LIFETIME/ROLLING, ACCEPT/REJECT, REJECT-rework/escalate, PASS/FAIL, HONOR/DENY, 4 classification cascades), all symmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 524
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
All 35 `errors[].id` also appear in §2/§3 prose (not just §5), and §2.2 is byte-identical to the canonical source.

### Ambiguities encountered (resolved conservatively, faithful to scaffold)
1. **Warranty-claim target state:** the endpoint description requires a `VERIFIED` order, but no validation entry names the rejection code. I mapped it to the generic state check `ERR_INVALID_STATE` rather than inventing an id.
2. **Pole self-loop transition** (`IN_SERVICE → IN_SERVICE` on SERVICEABLE/REJECT_ROUTINE) has precondition `pole.status IN {IN_SERVICE, MONITOR}` — I stated the cascade is permitted from both statuses while only condition fields update, without inventing a MONITOR exit rule.
3. **Early-bonus condition** is split across two calculation entries (season-window in `production_billing_amount`, `quality_score_lifetime >= 90.00` in `contractor_quality_score`); I expressed both as conjoined requirements in §3.9 step four.
4. **Backtick-extraction pitfall for future audits:** fenced code blocks (§2.2) break naive inline-backtick regex pairing — the audit must strip fenced blocks first (my first pass falsely reported 106 missing fields because of this).

## Step 5: Generate unit tests — 2026-08-13T05:30:00.000Z

Generation complete. Summary:

## What was generated

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/test_helpers/`):
- `types.py` — 16 enums + 10 entity TypedDicts; `BacklogSnapshot` correctly carries only `id`/`created_at` (no `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with 40 methods, one per PRD §4 endpoint
- `api_errors.py` — all 35 `ApiErrorId`s with the PRD §5 HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity asserters, `assert_budget_invariant` (total = available + committed + spent), `assert_instant_equals` (render-agnostic instant comparison), `assert_backlog_snapshot` (asserts absence of `version`/`updated_at`)
- `factories.py`, `constants.py` (all PRD calculation constants), `test_users.py` (4 opaque roles + entity-backed `make_contractor_headers(crew_id)` used for every ownership-gated apply/complete), `fixtures.py` (composite setups: open-cycle-with-task, submit/accept pipeline, treatment pipeline, `setup_crew_with_qa_history`, verified-order-with-claim, NOTIFIED-audit, funded-order, reconcile), `__init__.py` barrel

**`test_suite/`** — `conftest.py` + 9 test files, **95 tests**, all collecting cleanly with zero lint issues.

## Coverage
- **Queue A (Difficulty): 49 tests** — all 21 instances covered with ≥2 tests each (waterfall instance has 3)
- **Queue B (Corner): 46 tests** — all 46 covered non-stub instances with exactly 1 test each; all 11 `excluded_because:` stubs left untranslated, and every stub's `difficulty_instance` cross-reference verified to resolve
- Every test's docstring ends with exactly one verbatim `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line (programmatically audited)
- All 133 long PRD quotes in docstrings verified to survive literal grep of `workspace/PRD.md`
- No `skip`/`skipif`/`xfail` markers anywhere

## Instances skipped (PRD-first filter)
- **`Corner/entities/pole_system_fields_input_ignored`** — the instance asserts the server rejects a client-supplied `status` field with 400, but the PRD validation rules (§2.8 stage 3) cover only required-field presence, types, enums, and ranges; they never state whether extra/system fields are ignored or rejected. The instance's own name ("input_ignored") contradicts its assert ("rejected"), so two faithful PRD readers could ship either behavior. Gap left as a gap.

## Notable decisions
1. **REPLACED-pole setup path** (`submit_blocked_when_pole_replaced`): the design recipe completed a manual order on an `IN_SERVICE` pole, but PRD §3.8 describes the pole transition as `PRIORITY_REJECT → REPLACED`. To stay two-reader safe I drive the pole through the documented cascade instead (REJECT_PRIORITY accept → PRIORITY_REJECT → fund auto-created order → complete → REPLACED). Asserted rule unchanged.
2. **Billing fixture clock nudge**: PRD §3.9 scopes in-scope orders to `applied_at < reconcile instant`; with the frozen logical clock, apply and reconcile share an instant, so the fixture advances the clock one day before reconcile. Expected billing (99434) is unaffected.
3. **Version assertions are relative** (`version == created_version + 1`, per PRD §3.1 "increments the pole's `version` by one") rather than absolute `== 1`/`== 2`, since the PRD never pins the initial version value.
4. **`defer` on a FUNDED order asserts `ERR_ORDER_NOT_QUEUED`** — PRD §3.8 names that error for "an order not currently `QUEUED`" and §2.8 stage 5 lists it among state errors; judgment call kept because the error name encodes the precondition.

## Step 6: Generate implementation — 2026-08-13T05:10:00.000Z

Done. The implementation is complete and verified.

## Summary

**Files created** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/workspace/implementation/`):

- `start.sh` — guarded launcher (skips `pip install` when Flask is importable, `exec`s the server in foreground, binds `0.0.0.0:$PORT` default 10000)
- `requirements.txt` — flask
- `app.py` — Flask app, blueprint registration, envelope-wrapped error handlers
- `db.py` — in-memory stores (empty at boot, no seeding), logical clock starting exactly at `2026-08-01T00:00:00Z`, record/`touch` helpers
- `errors.py`, `response.py` — `ApiError` + the scaffold's exact envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more`)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, 5-role RBAC, write-lock decorator
- `validators.py` — staged field validation, `limit`/`offset` parsing (out-of-range → 400), filter helper
- `calc.py` — all 8 calculation rules in `Decimal` with half-up rounding
- `serializers.py` — per-entity field lists; datetimes → ISO 8601 with 3 fractional digits; `BacklogSnapshot` omits `updated_at`/`version`
- `routes/` — 11 modules: budgets, cycles, poles, tasks, treatments, claims, crews, replacements, audits, snapshots, clock

**Endpoint count: 40** (every row in the endpoint table, including `POST /pole-program/_clock/set_current_utc`).

**Notable implementation decisions:**
- **Validation pipeline order** follows PRD §2.8 strictly: auth → RBAC → body well-formedness → existence (path ids left-to-right, then body FKs in the PRD-listed order pole→cycle→crew→budget→treatment) → state → OCC → SOD/hazard → uniqueness/conflicts → temporal → photo evidence → fiscal capacity.
- **All money/percentage math in `Decimal`** with `ROUND_HALF_UP`; both strength variants stored, effective chosen by cycle policy; classification thresholds compared against the 2dp-rounded value.
- **Reconcile** implements the pinned 5-step order: program-wide DEFERRED→QUEUED requeue with priority recompute, overdue NOTIFIED→ESCALATED escalation, waterfall over program-wide QUEUED (priority DESC / created_at ASC, skip-and-continue, inclusive equality boundary), per-crew billing with per-line rounding before summation, bonus gated on both season-time and lifetime score ≥ 90 (PRD overrides scaffold here), then the immutable snapshot; budget version bumps on every reconcile.
- **Rework loop**: REJECT with `rework_count < 2` clears readings/photos/computed fields and lands directly back in OPEN (REJECTED is transient); the third reject → ESCALATED with `rework_count == 3`.
- **Crew quality**: event log ordered by `(decided_at, insertion seq)`; rolling window = last 5; suspension on FAIL when rolling < 70.00, reinstatement on PASS when rolling ≥ 70.00.
- **Fresh-boot contract verified**: three consecutive `start.sh` boots each start with an empty store and the clock at `2026-08-01T00:00:00.000Z`.
- Verified via ~100 live smoke checks covering CRUD, both strength variants, cascades (priority-reject order auto-creation, pole/crew/budget mutations), OCC 412s, warranty windows (inclusive boundary, Feb 29 → Feb 28), cure deadlines (+45d, exact-boundary allowed, 1ms-late rejected), waterfall skip-continue, billing totals to the cent, and pagination. All passing.

## Step 7: Run tests and iterate — 2026-08-13T05:55:00.000Z

All 8 rounds pass 95/95. The task is complete.

## Summary

- **Iterations run:** 2 (initial 8-round sweep → diagnosis + fix → confirmation 8-round sweep, all 8 rounds `passed == total` = 95/95 each).

- **Tests deleted:** none. Every test in the union of failures traced to PRD-verbatim rules (boundary classification §3.3, funding OCC §2.7/§3.8, audit parallel dimensions §3.7, deferral requeue §3.8/§3.9), and none tripped an assertion — no deletion criteria applied.

- **Fixes applied to `test_helpers/`:** none. Fixtures/factories/role headers were audited and are PRD-faithful (Contractor identity threading via `make_contractor_headers(crew_id)`, opaque PM/Inspector/QA IDs, PRD-shaped payloads).

- **Fixes applied to `implementation/`:** two files, both addressing the only failure mode found — flaky server-boot infrastructure under 8× parallel per-test-server restarts (12× "API server could not be restarted" 15s-poll timeouts + 1× `RemoteDisconnected` mid-test across the first sweep's 760 boots, clustered at the same wall-clock second across rounds, i.e., host contention spikes; zero assertion failures in any round):
  - `workspace/implementation/start.sh` — replaced the per-boot `python3 -c "import flask"` dependency probe (a full Python interpreter startup that could transiently fail under fork/exec starvation and fall into a multi-second `pip install`) with a `.deps_ok` marker-file fast path: install once, subsequent boots pay only a `stat(2)` before `exec python3 app.py`. Boot path went from two Python startups to one (~0.3s vs ~1.2s under 8× load).
  - `workspace/implementation/app.py` — (a) retry the werkzeug bind for up to 20s on `EADDRINUSE`, covering the window where the runner's SIGKILLed predecessor hasn't yet released the port (a dead boot there surfaced as the spurious restart timeout or a dirty old server answering the probe); (b) silence werkzeug's per-request access log (WARNING level) so request handling can't stall on log I/O under load.

No PRD-required behavior was added, removed, or weakened; the changes are boot/transport hardening only. Storage remains purely in-memory dicts, wiped on every `start.sh` re-invocation, and no entity data is seeded.

## Step 8: Finalize PRD — 2026-08-13T06:00:00.000Z

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/workspace/PRD_FINALIZED.md` — byte-identical to `PRD.md`.

**Line counts & delta:** PRD.md = 314 lines, PRD_FINALIZED.md = 314 lines, 0% delta. `diff -q` confirms IDENTICAL.

**Changes:** none. Zero edits were committed, so there are zero per-change bullets.

### Verification inspection (in lieu of per-edit search log — no edits were made)

Both Step 7 items were inspected for any API-observable behavioral choice before concluding the identical copy:

**Item 1 — `start.sh` `.deps_ok` marker fast path**
- (a) Subject: dependency-install boot path (skip the `python3 -c "import flask"` probe once deps are installed).
- (b) Paths enumerated: `grep -rn "deps_ok"` across `implementation/` — hits only in `start.sh:9,10,14` itself; no Python module reads the marker. Read `start.sh` in full (17 lines): the marker only gates the pip-install probe before `exec python3 app.py`. Confirmed `db.py` (in-memory storage) and `routes/clock.py` (logical-clock boot value per PRD §2.5) are untouched by it. Storage is still wiped per boot; no entity seeding.
- (c) Conclusion: pure process-boot mechanics. PRDs do not specify how a launcher installs dependencies; INSTRUCTION.md's contract ("installs dependencies, foreground server") is still satisfied. Nothing to pin.

**Item 2 — `app.py` werkzeug WARNING log level + EADDRINUSE bind retry**
- (a) Subject: server boot/socket-bind hardening and access-log verbosity.
- (b) Paths enumerated: `grep -rn "werkzeug\|EADDRINUSE\|setLevel\|logging"` — hits only at `app.py:42,48,61`, all inside the `if __name__ == "__main__":` block. Read `app.py` in full (65 lines): the log-level call (line 48) affects only stderr access-log emission, not response construction (`response.py` untouched); the retry loop (lines 55–64) wraps only `app.run(host="0.0.0.0", port=port)` with a 20s deadline and 0.1s backoff, re-raising non-EADDRINUSE errors. PORT env handling (`os.environ.get("PORT", "10000")`) and `0.0.0.0` binding match INSTRUCTION.md; the 20s retry window fits inside the 60s startup allowance. No route blueprint, error handler, serializer, or validation path is touched.
- (c) Conclusion: no request/response behavior, status code, or state-machine semantics altered. Nothing observable through the API to pin.

**Outcome:** the anticipated legitimate case held — both Step 7 fixes are boot/transport hardening with zero behavioral surface, so the correct PRD_FINALIZED.md is an exact copy of PRD.md. A fresh implementer reading PRD.md (equivalently PRD_FINALIZED.md) plus INSTRUCTION.md already has everything needed to reproduce the implementation's observable behavior; the boot-hardening details are launcher-internal and were correctly left unspecified.

## Step 9: Complete PRD — 2026-08-13T06:20:00.000Z

All edits verified. Final summary:

## Result

**File produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1399_utility_pole_inspection_treatment_program/workspace/PRD_COMPLETED.md`

**Source vs completed:** `PRD_FINALIZED.md` 314 lines / 52,979 chars → `PRD_COMPLETED.md` 315 lines / 55,390 chars (**+1 line, +2,411 chars**, 25 diff hunks, all inline).

**Counts:** 27 ambiguity-pins (28 edit sites; the §5 catalogue row is the companion of the §2.9 pin) and 3 mismatch-revisions.

### Ambiguity-pins (insert)
- §2.3 — insert — ambiguity — invalid/out-of-range `limit` or negative `offset` rejected with `ERR_INVALID_REQUEST` — implementation/validators.py:102-121
- §2.3 — insert — ambiguity — list sort ties on identical `created_at` break by creation order (`_seq`) — implementation/validators.py:135
- §2.3 — insert — ambiguity — `has_more` = `offset + returned items < total_count` — implementation/response.py:28
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — implementation/db.py:47
- §2.5 — insert — ambiguity — clock set accepts any parseable instant, no monotonicity constraint — implementation/routes/clock.py:19
- §2.8 — insert — ambiguity — blanket rule: §3 state preconditions without a more specific code reject with `ERR_INVALID_STATE` (covers open/reconcile non-DRAFT/OPEN, submit/waive non-OPEN, schedule/apply/qa states, defund/complete, claim/audit adjudicate, mark-cured) — e.g. implementation/routes/cycles.py:71, routes/treatments.py:91,138,158, routes/replacements.py:109,148, routes/claims.py:81, routes/audits.py:49,69
- §2.9 — insert — ambiguity — snapshot 404 resolves to `ERR_SNAPSHOT_NOT_FOUND` — implementation/routes/snapshots.py:30
- §2.9 — insert — ambiguity — undefined route/method → `ERR_NOT_FOUND` (404/405), unexpected failure → `ERR_INTERNAL` (500) — implementation/app.py:23-37
- §5 — insert — ambiguity — added `ERR_SNAPSHOT_NOT_FOUND` | 404 row to the error catalogue (companion of the §2.9 pin)
- §3.1 — insert — ambiguity — `gis_lat`/`gis_lon` validated as numbers only, no coordinate range check — implementation/routes/poles.py:28-29
- §3.1 — insert — ambiguity — GIS patch payload must supply all three attributes plus `expected_pole_version` — implementation/routes/poles.py:69-73
- §3.1 — insert — ambiguity — `sample_pct` accepts fractional values — implementation/routes/cycles.py:38
- §3.1 — insert — ambiguity — `pending_replacement_count` counts the cycle's orders in `QUEUED`/`DEFERRED`/`FUNDED` — implementation/serializers.py:56-58
- §3.2 — insert — ambiguity — eligibility recency measured anniversary-to-anniversary with Feb 29 → Feb 28 convention — implementation/routes/cycles.py:81, calc.py:46-51
- §3.2 — insert — ambiguity — pool ranking ties beyond `created_at` break by creation order — implementation/routes/cycles.py:92-95
- §3.3 — insert — ambiguity — `photos` is a required field; each entry's `taken_at` carried as an opaque string (no datetime parse) — implementation/routes/tasks.py:106-112
- §3.3 — insert — ambiguity — only `sound_wood_pct` is range-bounded; `shell_thickness_in`, `decay_pocket_depth_in`, `moisture_pct` accept any number — implementation/routes/tasks.py:100-103
- §3.3 — insert — ambiguity — `found_attachment_count` optional, non-negative when present, ignored for non-joint-use poles, omitted value records 0 on the audit — implementation/routes/tasks.py:113-115,150-151
- §3.4 — insert — ambiguity — task QA-review `notes` accepted but not persisted — implementation/routes/tasks.py:179-180
- §3.4 — insert — ambiguity — ACCEPT cascade against an already-`PRIORITY_REJECT` pole updates condition fields only; no further order created — implementation/routes/tasks.py:199-206
- §3.4 — insert — ambiguity — reject-clearing also resets the hazard flag — implementation/routes/tasks.py:214
- §3.5 — insert — ambiguity — `current_cycle_billing_cents` is zero until a reconcile first bills the crew — implementation/routes/crews.py:31
- §3.5 — insert — ambiguity — treatment QA-review `notes` accepted but not persisted — implementation/routes/treatments.py:155
- §3.6 — insert — ambiguity — HONOR retreat creation runs no pole-status guard (retreat created even if pole since `REPLACED`) — implementation/routes/claims.py:86-98
- §3.8 — insert — ambiguity — `priority_score` rounded half-up to a whole integer after floor and cap — implementation/calc.py:152
- §3.8 — insert — ambiguity — defund also clears `funded_at` to null — implementation/routes/replacements.py:117
- §3.8 — insert — ambiguity — deferring a non-`QUEUED` order rejected with `ERR_ORDER_NOT_QUEUED` — implementation/routes/replacements.py:128-130
- §3.9 — insert — ambiguity — waterfall ranking ties beyond `created_at` break by creation order — implementation/routes/cycles.py:152-154
- §3.9 — insert — ambiguity — `crew_billings` array ordered by crew creation — implementation/routes/cycles.py:171-172

### Mismatch-revisions (revise)
- §3.5 — revise — mismatch — `qa_event_log` tie-break changed from "event's `created_at`" (events carry no `created_at`) to append order — implementation/calc.py:176-177
- §3.6 — revise — mismatch — `adjudication_note` is recorded when supplied on either outcome, not only on `DENY` — implementation/routes/claims.py:82-83
- §3.8 — revise — mismatch — completion moves the pole to `REPLACED` regardless of prior status (impl sets unconditionally; manual orders can target non-`PRIORITY_REJECT` poles), not strictly "from `PRIORITY_REJECT`" — implementation/routes/replacements.py:158-161

No new sections were added; all changes are in-paragraph inserts/revisions plus one row in the existing §5 table. Every endpoint, state transition, formula, validation, error path, default, side effect, and ordering rule in `implementation/` is now uniquely pinned by the PRD.
