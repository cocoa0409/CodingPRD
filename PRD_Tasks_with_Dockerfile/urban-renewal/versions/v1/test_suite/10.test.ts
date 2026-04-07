import { v4 as uuidv4 } from 'uuid';
import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  createContractPayload,
  getSuccessData,
  UrbanRenewalProject,
  RenovationPhase,
  WorkOrder,
  RenovationCrew,
  CrewContract,
} from '../../../test-helpers';
import { validateErrorEnvelope } from '../../../test-helpers/validators';
import { ApiErrorId } from '../../../test-helpers/api-errors';

describe('Phase 2 — Batch Operations', () => {
  describe('Work Order Batch', () => {
    it('all valid items → 201 array in input order', async () => {
      const headers = buildAuthHeaders('batch-user-1');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },
        { task_type: 'B', start_hour: 20, end_hour: 30, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },
      ];
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      expect(res.status).toBe(201);
      const orders = getSuccessData<WorkOrder[]>(res);
      expect(orders.length).toBe(2);
      expect(orders[0].task_type).toBe('A');
      expect(orders[1].task_type).toBe('B');
    });

    it('single invalid item → 409 ERR_BATCH_REJECTED; no items created', async () => {
      const headers = buildAuthHeaders('batch-user-2');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },

        { task_type: 'B', start_hour: 5, end_hour: 5, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },
      ];
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });

    it('single invalid item at the first position → 409 ERR_BATCH_REJECTED; no items created', async () => {
      const headers = buildAuthHeaders('batch-user-2a');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const items = [

        { task_type: 'X', start_hour: 10, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },
        { task_type: 'Y', start_hour: 20, end_hour: 30, required_specialization: 'GENERAL', required_safety_clearance_level: 1 },
      ];
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });

    it('malformed per-item idempotency_key → 409 ERR_BATCH_REJECTED; no items created', async () => {
      const headers = buildAuthHeaders('batch-user-2b');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: 'not-a-uuid' as any },
      ];
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });

    it('conflicting duplicate per-item key in single payload → 409 ERR_BATCH_REJECTED; no items created', async () => {
      const headers = buildAuthHeaders('batch-user-2c');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const key = uuidv4();
      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: key },

        { task_type: 'A', start_hour: 1, end_hour: 11, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: key },
      ];
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });

    it('per-item idempotency replay: 200 replay with identical resources', async () => {
      const headers = buildAuthHeaders('batch-user-4');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const id1 = uuidv4();
      const id2 = uuidv4();
      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: id1 },
        { task_type: 'B', start_hour: 20, end_hour: 30, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: id2 },
      ];
      const first = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      expect(first.status).toBe(201);
      const created = getSuccessData<WorkOrder[]>(first);
      const second = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      expect(second.status).toBe(200);
      const replayed = getSuccessData<WorkOrder[]>(second);
      expect(replayed.map(o => o.id)).toEqual(created.map(o => o.id));
    });

    it('mixed replay with changed item under same key → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-5');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const id1 = uuidv4();
      const id2 = uuidv4();
      const base = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: id1 },
        { task_type: 'B', start_hour: 20, end_hour: 30, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: id2 },
      ];
      const first = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items: base }, headers);
      expect(first.status).toBe(201);

      const mixed = [ base[0], { ...base[1], start_hour: 100 } ];
      const second = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items: mixed }, headers);
      validateErrorEnvelope(second, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
    });

    it('batch-level Idempotency-Key replay returns cached success with meta.idempotency_replay:true', async () => {
      const headers = buildAuthHeaders('batch-user-6');
      const key = uuidv4();
      const idempHeaders = { ...headers, 'Idempotency-Key': key };
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), idempHeaders));
      getSuccessData(await apiClient.beginWork(project.id, idempHeaders));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), idempHeaders));
      const items = [ { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1 } ];
      const first = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, idempHeaders);
      expect(first.status).toBe(201);
      const second = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, idempHeaders);
      expect(second.status).toBe(200);
      const env = second.data as any;
      expect(env.meta.idempotency_replay).toBe(true);
    });

    it('work orders per-item duplicate identical keys in single payload → 201; echoed twice', async () => {
      const headers = buildAuthHeaders('batch-user-dup-wo');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const key = uuidv4();
      const baseItem = { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: key };
      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items: [baseItem, { ...baseItem }] }, headers);
      expect(res.status).toBe(201);
      const orders = getSuccessData<WorkOrder[]>(res);
      expect(orders).toHaveLength(2);
      expect(orders[0].id).toBe(orders[1].id);
    });

    it('work orders per-item duplicate conflicting payloads → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-dup-conflict');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const key = uuidv4();
      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: key },
        { task_type: 'A', start_hour: 0, end_hour: 12, required_specialization: 'GENERAL', required_safety_clearance_level: 1, idempotency_key: key }
      ];

      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });

    it('non-integer required_safety_clearance_level in batch → 409 ERR_BATCH_REJECTED; no work orders created', async () => {
      const headers = buildAuthHeaders('batch-user-nonint');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));

      const items = [
        { task_type: 'A', start_hour: 0, end_hour: 10, required_specialization: 'GENERAL', required_safety_clearance_level: 1.5 }
      ];

      const res = await apiClient.batchCreateWorkOrders(project.id, phase.id, { items }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<WorkOrder[]>(await apiClient.getWorkOrders(project.id, phase.id, headers));
      expect(list.length).toBe(0);
    });
  });

  describe('Contract Batch', () => {
    it('all valid → 201; work orders move to AWAITING_CONFIRMATION', async () => {
      const headers = buildAuthHeaders('batch-user-7');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));
      const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
      const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));

      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo1.id, crew_id: crew.id }, { work_order_id: wo2.id, crew_id: crew.id } ] }, headers);
      expect(res.status).toBe(201);
      const contracts = getSuccessData<CrewContract[]>(res);
      expect(contracts.length).toBe(2);

      const get1 = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo1.id, headers));
      const get2 = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo2.id, headers));
      expect(get1.status).toBe('AWAITING_CONFIRMATION');
      expect(get2.status).toBe('AWAITING_CONFIRMATION');
    });

    it('single invalid foreign key → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-8');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));

      const badId = '00000000-0000-0000-0000-000000000000';
      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: badId, crew_id: badId } ] }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
    });

    it('budget sum exceeds remaining → 409 ERR_BATCH_REJECTED; no ledger changes', async () => {
      const headers = buildAuthHeaders('batch-user-9');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ renovation_budget: 1000 }), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));
      const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
      const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));
      const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo1.id, crew_id: crew.id }, { work_order_id: wo2.id, crew_id: crew.id } ] }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const list = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      expect(list.length).toBe(0);
      const after = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(after.budget_balance).toBe(before.budget_balance);
      expect(after.community_disruption_index).toBe(before.community_disruption_index);
    });

    it('disruption sum breaches threshold without waivers → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-10');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

      for (let i = 0; i < 3; i++) {
        const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: i*300, end_hour: i*300 + 200 }), headers));
        getSuccessData(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
      }

      const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 1000, end_hour: 1200 }), headers));
      const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 1300, end_hour: 1500 }), headers));

      const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      const existingContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo1.id, crew_id: crew.id }, { work_order_id: wo2.id, crew_id: crew.id } ] }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const afterContracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      expect(afterContracts.length).toBe(existingContracts.length);
      const after = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(after.budget_balance).toBe(before.budget_balance);
      expect(after.community_disruption_index).toBe(before.community_disruption_index);
    });

    it('waiver allows hazardous item when threshold would be breached; penalty applied', async () => {
      const headers = buildAuthHeaders('batch-user-11');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ hourly_rate: 100 }), headers));

      for (let i = 0; i < 4; i++) {
        const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: i*300, end_hour: i*300 + 200 }), headers));
        getSuccessData(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
      }

      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 2000, end_hour: 2200 }), headers));
      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo.id, crew_id: crew.id, permit_waiver_used: true } ] }, headers);
      expect(res.status).toBe(201);
      const contracts = getSuccessData<CrewContract[]>(res);
      expect(contracts.length).toBe(1);
      expect(contracts[0].permit_waiver_penalty_applied).toBe(true);
    });

    it('duplicate work_order in items → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-12');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
      const res = await apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo.id, crew_id: crew.id }, { work_order_id: wo.id, crew_id: crew.id } ] }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
    });

    it('duplicate work_order_id with different idempotency keys → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-12b');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew1' }), headers));
      const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew2' }), headers));
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));

      const k1 = uuidv4();
      const k2 = uuidv4();
      const res = await apiClient.batchCreateContracts(project.id, {
        items: [
          { work_order_id: wo.id, crew_id: crew1.id, idempotency_key: k1 },
          { work_order_id: wo.id, crew_id: crew2.id, idempotency_key: k2 }
        ]
      }, headers);
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      expect(contracts.length).toBe(0);
    });

    it('per-item idempotency replay: 200 replay with identical IDs', async () => {
      const headers = buildAuthHeaders('batch-user-13');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
      const altCrew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'AltCrew' }), headers));
      const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
      const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 20, end_hour: 30 }), headers));

      const k1 = uuidv4();
      const k2 = uuidv4();
      const items = [ { work_order_id: wo1.id, crew_id: crew.id, idempotency_key: k1 }, { work_order_id: wo2.id, crew_id: crew.id, idempotency_key: k2 } ];
      const first = await apiClient.batchCreateContracts(project.id, { items }, headers);
      const created = getSuccessData<CrewContract[]>(first);
      const second = await apiClient.batchCreateContracts(project.id, { items }, headers);
      expect(second.status).toBe(200);
      const replayed = getSuccessData<CrewContract[]>(second);
      expect(replayed.map(c => c.id)).toEqual(created.map(c => c.id));
    });

    it('batch-level Idempotency-Key: replay returns cached success with meta.idempotency_replay:true', async () => {
      const headers = buildAuthHeaders('batch-user-14');
      const key = uuidv4();
      const H = { ...headers, 'Idempotency-Key': key };
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), H));
      getSuccessData(await apiClient.beginWork(project.id, H));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), H));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), H));
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), H));

      const items = [ { work_order_id: wo.id, crew_id: crew.id } ];
      const first = await apiClient.batchCreateContracts(project.id, { items }, H);
      expect(first.status).toBe(201);
      const second = await apiClient.batchCreateContracts(project.id, { items }, H);
      expect(second.status).toBe(200);
      const env = second.data as any;
      expect(env.meta.idempotency_replay).toBe(true);
    });

    it('mixed replay with altered item payload under same key → 409 ERR_BATCH_REJECTED', async () => {
      const headers = buildAuthHeaders('batch-user-15');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
      const altCrew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'AltCrew' }), headers));
      const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));
      const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 50, end_hour: 60 }), headers));

      const k1 = uuidv4();
      const k2 = uuidv4();
      const base = [ { work_order_id: wo1.id, crew_id: crew.id, idempotency_key: k1 }, { work_order_id: wo2.id, crew_id: crew.id, idempotency_key: k2 } ];
      const first = await apiClient.batchCreateContracts(project.id, { items: base }, headers);
      expect(first.status).toBe(201);

      const changed = [ base[0], { ...base[1], crew_id: altCrew.id } ];
      const second = await apiClient.batchCreateContracts(project.id, { items: changed }, headers);
      validateErrorEnvelope(second, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
    });

    it('two concurrent contract batches overlapping work_orders → exactly one batch succeeds; other 409', async () => {
      const headers = buildAuthHeaders('batch-user-16');
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
      const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));
      const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers));

      const batchA = apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo.id, crew_id: crew.id } ] }, headers);
      const batchB = apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: wo.id, crew_id: crew.id } ] }, headers);
    const [a, b] = await Promise.all([batchA, batchB]);

    const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
    const rejectCount = [a.status, b.status].filter(s => s === 409).length;
    expect(okCount).toBe(1);
    expect(rejectCount).toBe(1);
    const loser = a.status === 409 ? a : b;
    validateErrorEnvelope(loser as any, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
    const all = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
    expect(all.filter(c => c.work_order_id === wo.id).length).toBe(1);
    const woAfter = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo.id, headers));
    expect(woAfter.status).toBe('AWAITING_CONFIRMATION');
  });

  it('concurrent single POST and batch targeting same work_order → exactly one path succeeds', async () => {
      const headers = buildAuthHeaders('batch-user-17');
      const project = getSuccessData<UrbanRenewalProject>(
        await apiClient.createProject(createProjectPayload({ project_name: 'BatchRace' }), headers)
      );
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(
        await apiClient.createPhase(project.id, createPhasePayload(), headers)
      );
      const crew = getSuccessData<RenovationCrew>(
        await apiClient.createCrew(project.id, createCrewPayload(), headers)
      );
      const order = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload(), headers)
      );

      const single = apiClient.createContract(project.id, { work_order_id: order.id, crew_id: crew.id }, headers);
      const batch = apiClient.batchCreateContracts(project.id, { items: [ { work_order_id: order.id, crew_id: crew.id } ] }, headers);

      const [a, b] = await Promise.all([single, batch]);
      const okCount = [a.status, b.status].filter(s => s >= 200 && s < 300).length;
      const conflictCount = [a.status, b.status].filter(s => s === 409).length;
      expect(okCount).toBe(1);
      expect(conflictCount).toBe(1);
      const loser = a.status === 409 ? a : b;
      if (loser === a) {
        validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_WORK_ORDER_NOT_PENDING });
      } else {
        validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });
      }
      const all = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      expect(all.filter(c => c.work_order_id === order.id).length).toBe(1);
      const orderAfter = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, order.id, headers));
      expect(orderAfter.status).toBe('AWAITING_CONFIRMATION');
  });

  it('contracts per-item mixed replay + new → 201; order preserved', async () => {
    const headers = buildAuthHeaders('batch-user-24');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 12, end_hour: 20 }), headers));
    const wo3 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 24, end_hour: 30 }), headers));

    const id1 = uuidv4();
    const id2 = uuidv4();
    const firstItems = [ { work_order_id: wo1.id, crew_id: crew.id, idempotency_key: id1 }, { work_order_id: wo2.id, crew_id: crew.id, idempotency_key: id2 } ];
    const first = await apiClient.batchCreateContracts(project.id, { items: firstItems }, headers);
    expect(first.status).toBe(201);
    const created = getSuccessData<CrewContract[]>(first);

    const id3 = uuidv4();

    const secondItems = [ { work_order_id: wo1.id, crew_id: crew.id, idempotency_key: id1 }, { work_order_id: wo3.id, crew_id: crew.id, idempotency_key: id3 } ];
    const second = await apiClient.batchCreateContracts(project.id, { items: secondItems }, headers);
    expect(second.status).toBe(201);
    const out = getSuccessData<CrewContract[]>(second);
    expect(out).toHaveLength(2);
    expect(out[0].id).toBe(created[0].id);
    expect(out[1].id).not.toBe(created[0].id);
    expect(out[1].id).not.toBe(created[1].id);
  });

    it('contracts per-item duplicate identical keys in single payload → 201; echoed twice', async () => {
    const headers = buildAuthHeaders('batch-user-25');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
    const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const key = uuidv4();
    const items = [ { work_order_id: wo.id, crew_id: crew.id, idempotency_key: key }, { work_order_id: wo.id, crew_id: crew.id, idempotency_key: key } ];
    const res = await apiClient.batchCreateContracts(project.id, { items }, headers);
    expect(res.status).toBe(201);
    const arr = getSuccessData<CrewContract[]>(res);
    expect(arr).toHaveLength(2);
      expect(arr[0].id).toBe(arr[1].id);
    });

    it('item requiring specialization without crew cert → 409 ERR_BATCH_REJECTED; atomic (no side effects)', async () => {
      const headers = buildAuthHeaders('batch-user-26');
      const project = getSuccessData<UrbanRenewalProject>(
        await apiClient.createProject(createProjectPayload({ project_name: 'BatchCertMismatch' }), headers)
      );
      getSuccessData(await apiClient.beginWork(project.id, headers));
      const phase = getSuccessData<RenovationPhase>(
        await apiClient.createPhase(project.id, createPhasePayload(), headers)
      );
      const crew = getSuccessData<RenovationCrew>(
        await apiClient.createCrew(project.id, createCrewPayload({  }), headers)
      );
      const wo1 = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({ required_specialization: 'ELECTRICAL' as any, required_safety_clearance_level: 1 }),
          headers
        )
      );
      const wo2 = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({ required_specialization: 'PLUMBING' as any, required_safety_clearance_level: 1, start_hour: wo1.end_hour + 4, end_hour: wo1.end_hour + 8 }),
          headers
        )
      );

      const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));

      const res = await apiClient.batchCreateContracts(
        project.id,
        {
          items: [
            { work_order_id: wo1.id, crew_id: crew.id },
            { work_order_id: wo2.id, crew_id: crew.id },
          ],
        },
        headers
      );
      validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_BATCH_REJECTED });

      const contracts = getSuccessData<CrewContract[]>(await apiClient.getContracts(project.id, headers));
      expect(contracts.length).toBe(0);

      const w1 = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo1.id, headers));
      const w2 = getSuccessData<WorkOrder>(await apiClient.getWorkOrder(project.id, phase.id, wo2.id, headers));
      expect(w1.status).toBe('PENDING');
      expect(w2.status).toBe('PENDING');

      const after = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
      expect(after.budget_balance).toBe(before.budget_balance);
    });
  });
});
