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
import { validateApiResponseStructure, validateErrorEnvelope } from '../../../test-helpers/validators';
import { ApiErrorId } from '../../../test-helpers/api-errors';

function uniqueCount(included: any[], type: string): number {
  const set = new Set(included.filter(i => i.type === type).map(i => `${i.type}:${i.id}`));
  return set.size;
}

describe('Phase 2 — Performance (Include-based N+1 prevention)', () => {
  it('GET /projects?include=phases,crews → includes deduped relateds with exact counts', async () => {
    const headers = buildAuthHeaders('perf-user-1');
    const projectCount = 6;
    const phasesPer = 3;
    const crewsPer = 2;
    const createdProjectIds: string[] = [];
    const expectedPhaseIds: string[] = [];
    const expectedCrewIds: string[] = [];

    for (let p = 0; p < projectCount; p++) {
      const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: `P${p}` }), headers));
      getSuccessData(await apiClient.beginWork(project.id, headers));
      createdProjectIds.push(project.id);
      for (let i = 0; i < phasesPer; i++) {
        const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: `P${p}-Phase${i}` }), headers));
        expectedPhaseIds.push(phase.id);
      }
      for (let j = 0; j < crewsPer; j++) {
        const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: `P${p}-Crew${j}` }), headers));
        expectedCrewIds.push(crew.id);
      }
    }

    const res = await apiClient.getProjectsWithParams({ include: 'phases,crews' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    const expectedPhases = projectCount * phasesPer;
    const expectedCrews = projectCount * crewsPer;
    const projectIdSet = new Set(createdProjectIds);
    const includedPhaseIds = included
      .filter(i => i.type === 'phase' && projectIdSet.has(i.project_id))
      .map(i => i.id);
    const includedCrewIds = included
      .filter(i => i.type === 'crew' && projectIdSet.has(i.project_id))
      .map(i => i.id);
    expect(new Set(includedPhaseIds).size).toBe(expectedPhases);
    expect(new Set(includedCrewIds).size).toBe(expectedCrews);
    expect([...new Set(includedPhaseIds)].sort()).toEqual([...new Set(expectedPhaseIds)].sort());
    expect([...new Set(includedCrewIds)].sort()).toEqual([...new Set(expectedCrewIds)].sort());
    const setAll = new Set(included.map(i => `${i.type}:${i.id}`));
    expect(setAll.size).toBe(included.length);
  });

  it('GET /projects/{projId}/phases?include=work_orders,work_orders.contracts → exact unique counts', async () => {
    const headers = buildAuthHeaders('perf-user-2');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'Nested' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({}), headers));

    const phases: RenovationPhase[] = [];
    for (let i = 0; i < 10; i++) {
      phases.push(getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload({ name: `Ph-${i}` }), headers)));
    }

    let nextStart = 0;
    const allWO: WorkOrder[] = [];
    for (const ph of phases) {
      for (let k = 0; k < 5; k++) {
        const wo = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, ph.id, createWorkOrderPayload({ start_hour: nextStart, end_hour: nextStart + 1 }), headers));
        allWO.push(wo);
        nextStart += 2;
        getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers));
      }
    }

    const res = await apiClient.getPhasesWithParams(project.id, { include: 'work_orders,work_orders.contracts' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    const expectedWO = phases.length * 5;
    const expectedContracts = expectedWO;
    expect(uniqueCount(included, 'work_order')).toBe(expectedWO);
    expect(uniqueCount(included, 'contract')).toBe(expectedContracts);
  });

  it('GET /projects/{projId}/phases?include=work_orders.contracts → includes both work_orders and their contracts', async () => {
    const headers = buildAuthHeaders('perf-user-2b');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'ContractsOnly' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload(), headers));

    const wA = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 1 }), headers));
    const wB = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 4, end_hour: 5 }), headers));
    getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wA.id, crew.id), headers));
    getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wB.id, crew.id), headers));

    const res = await apiClient.getPhasesWithParams(project.id, { include: 'work_orders.contracts' }, headers);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    expect(uniqueCount(included, 'contract')).toBe(2);
    expect(uniqueCount(included, 'work_order')).toBe(2);
    const setAll = new Set(included.map(i => `${i.type}:${i.id}`));
    expect(setAll.size).toBe(included.length);
  });

  it('GET /projects/{projId}/contracts?include=work_order,crew → dedup enforced', async () => {
    const headers = buildAuthHeaders('perf-user-3');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'CIncl' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const phase = getSuccessData<RenovationPhase>(await apiClient.createPhase(project.id, createPhasePayload(), headers));
    const crew = getSuccessData<RenovationCrew>(await apiClient.createCrew(project.id, createCrewPayload({ crew_name: 'Crew-X' }), headers));

    const wo1 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 0, end_hour: 10 }), headers));
    const wo2 = getSuccessData<WorkOrder>(await apiClient.createWorkOrder(project.id, phase.id, createWorkOrderPayload({ start_hour: 12, end_hour: 20 }), headers));
    const c1 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo1.id, crew.id), headers));
    const c2 = getSuccessData<CrewContract>(await apiClient.createContract(project.id, createContractPayload(wo2.id, crew.id), headers));

    const res = await apiClient.getContractsWithParams(project.id, { include: 'work_order,crew' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    expect(uniqueCount(included, 'work_order')).toBe(2);
    expect(uniqueCount(included, 'crew')).toBe(1);
  });

  it('invalid include value → 400 ERR_INVALID_REQUEST', async () => {
    const headers = buildAuthHeaders('perf-user-4');
    const res = await apiClient.getProjectsWithParams({ include: 'foo' }, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
  });

  it('GET /projects/{projId}/phases invalid include → 400 ERR_INVALID_REQUEST', async () => {
    const headers = buildAuthHeaders('perf-user-5');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const res = await apiClient.getPhasesWithParams(project.id, { include: 'foo' }, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
  });

  it('GET /projects/{projId}/contracts invalid include → 400 ERR_INVALID_REQUEST', async () => {
    const headers = buildAuthHeaders('perf-user-6');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({}), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const res = await apiClient.getContractsWithParams(project.id, { include: 'foo' }, headers);
    validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INVALID_REQUEST });
  });

  it('include present but no relateds → included: [] for GET /projects', async () => {
    const headers = buildAuthHeaders('perf-user-7');
    const emptyProject = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'EmptyProj' }), headers));
    const res = await apiClient.getProjectsWithParams({ include: 'phases,crews,contracts' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    const relatedForProject = included.filter((item: any) => item.project_id === emptyProject.id);
    expect(relatedForProject.length).toBe(0);
  });

  it('include present with no relateds → included: [] for GET /projects/{projId}/phases', async () => {
    const headers = buildAuthHeaders('perf-user-8');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'EmptyPhases' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const res = await apiClient.getPhasesWithParams(project.id, { include: 'work_orders,work_orders.contracts' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    expect(included.length).toBe(0);
  });

  it('include present with no relateds → included: [] for GET /projects/{projId}/contracts', async () => {
    const headers = buildAuthHeaders('perf-user-9');
    const project = getSuccessData<UrbanRenewalProject>(await apiClient.createProject(createProjectPayload({ project_name: 'EmptyContracts' }), headers));
    getSuccessData(await apiClient.beginWork(project.id, headers));
    const res = await apiClient.getContractsWithParams(project.id, { include: 'work_order,crew' }, headers);
    const env = validateApiResponseStructure<any>(res);
    const included = (res.data as any).included as any[];
    expect(Array.isArray(included)).toBe(true);
    expect(included.length).toBe(0);
  });
});
