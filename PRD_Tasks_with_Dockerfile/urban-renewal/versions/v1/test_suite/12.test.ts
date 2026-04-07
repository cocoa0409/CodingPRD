import {
  apiClient,
  buildAuthHeaders,
  createProjectPayload,
  createPhasePayload,
  createWorkOrderPayload,
  createCrewPayload,
  createCrewConflictPairingPayload,
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

describe('Phase 2 — Crew Conflict Pairings', () => {
  const expectSortedByCreatedAtThenId = (entries: Array<{ created_at: string; id: string }>) => {
    for (let i = 1; i < entries.length; i++) {
      const prevTime = Date.parse(entries[i - 1].created_at);
      const currTime = Date.parse(entries[i].created_at);
      expect(prevTime).toBeLessThanOrEqual(currTime);
    }
  };
  it('creating contracts for paired crews in same phase → 409 ERR_CREW_CONFLICT for the second', async () => {
    const headers = buildAuthHeaders('pair-user-1');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'C1' }), headers));
    const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'C2' }), headers));
    getSuccessData(await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew1.id, crew2.id), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));

    const first = await apiClient.createContract(project.id, createContractPayload(wo1.id, crew1.id), headers);
    expect(first.status).toBe(201);
    const second = await apiClient.createContract(project.id, createContractPayload(wo2.id, crew2.id), headers);
    validateErrorEnvelope(second, { expectedErrorId: ApiErrorId.ERR_CREW_CONFLICT });
  });

  it('pairings are project-local; different project without pairing allows both contracts', async () => {
    const headers = buildAuthHeaders('pair-user-2');
    const p1 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'P1' }), headers));
    const p2 = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'P2' }), headers));
    getSuccessData(await apiClient.beginWork(p1.id, headers));
    getSuccessData(await apiClient.beginWork(p2.id, headers));
    const ph1 = getSuccessData<RenovationPhase>(await apiClient.createPhase(p1.id, createPhasePayload(), headers));
    const ph2 = getSuccessData<RenovationPhase>(await apiClient.createPhase(p2.id, createPhasePayload(), headers));
    const crewA1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(p1.id, createCrewPayload({ crew_name: 'A1' }), headers));
    const crewB1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(p1.id, createCrewPayload({ crew_name: 'B1' }), headers));
    getSuccessData(await apiClient.createCrewConflictPairing(p1.id, createCrewConflictPairingPayload(crewA1.id, crewB1.id), headers));

    const crewA2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(p2.id, createCrewPayload({ crew_name: 'A2' }), headers));
    const crewB2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(p2.id, createCrewPayload({ crew_name: 'B2' }), headers));

    const w2a = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(p2.id, ph2.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const w2b = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(p2.id, ph2.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));

    const rA = await apiClient.createContract(p2.id, createContractPayload(w2a.id, crewA2.id), headers);
    const rB = await apiClient.createContract(p2.id, createContractPayload(w2b.id, crewB2.id), headers);
    expect(rA.status).toBe(201);
    expect(rB.status).toBe(201);
  });

  it('self-pairing invalid → 400 ERR_SELF_PAIRING', async () => {
    const headers = buildAuthHeaders('pair-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));
    const res = await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew.id, crew.id), headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_SELF_PAIRING });
  });

  it('bad pairId path → 404 ERR_PAIRING_NOT_FOUND', async () => {
    const headers = buildAuthHeaders('pair-user-4');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const BAD = '00000000-0000-0000-0000-000000000000';
    const res = await apiClient.getCrewConflictPairing(project.id, BAD, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_PAIRING_NOT_FOUND });
  });

  it('GET /projects/{projId}/crew-conflict-pairings is sorted by created_at asc', async () => {
    const headers = buildAuthHeaders('pair-user-sort');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const crew1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'S1' }), headers));
    const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'S2' }), headers));
    const crew3 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'S3' }), headers));

    getSuccessData(await apiClient.createCrewConflictPairing(project.id, { crew_id_1: crew1.id, crew_id_2: crew2.id }, headers));
    getSuccessData(await apiClient.createCrewConflictPairing(project.id, { crew_id_1: crew2.id, crew_id_2: crew3.id }, headers));

    const list = getSuccessData(await apiClient.getCrewConflictPairings(project.id, headers));
    expect(list.length).toBeGreaterThanOrEqual(2);
    expectSortedByCreatedAtThenId(list.map((i: any) => ({ created_at: i.created_at, id: i.id })));
  });

  it('conflict scope limited to phase: paired crews in different phases can both create contracts', async () => {
    const headers = buildAuthHeaders('pair-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase1 = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: 'P1' }), headers));
    const phase2 = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: 'P2' }), headers));
    const crew1 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'C1' }), headers));
    const crew2 = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'C2' }), headers));
    getSuccessData(await apiClient.createCrewConflictPairing(project.id, createCrewConflictPairingPayload(crew1.id, crew2.id), headers));

    const w1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase1.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const w2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase2.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));

    const r1 = await apiClient.createContract(project.id, createContractPayload(w1.id, crew1.id), headers);
    const r2 = await apiClient.createContract(project.id, createContractPayload(w2.id, crew2.id), headers);
    expect(r1.status).toBe(201);
    expect(r2.status).toBe(201);
  });
});
