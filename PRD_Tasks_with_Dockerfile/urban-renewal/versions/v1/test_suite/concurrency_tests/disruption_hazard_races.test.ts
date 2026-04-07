import {
  apiClient,
  buildAuthHeaders,
  createContractPayload,
  createCrewPayload,
  createPhasePayload,
  createProjectPayload,
  createWorkOrderPayload,
  getSuccessData,
  CrewContract,
  RenovationCrew,
  RenovationPhase,
  UrbanRenewalProject,
  WorkOrder,
} from '../../../../test-helpers';
import { validateErrorEnvelope } from '../../../../test-helpers/validators';
import { ApiErrorId } from '../../../../test-helpers/api-errors';

const HAZARD_THRESHOLD = 160;
const DISRUPTION_INDEX_INCREMENT = 25;
const DISRUPTION_INDEX_THRESHOLD = 100;
const WAIVER_PENALTY = 75;

describe('Concurrency — Disruption Index & Hazardous Pay Races', () => {
  it('disruption threshold race: two hazardous proposals near 100 → one 201, one 403', async () => {
    const headers = buildAuthHeaders('hazard-near-100');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Hazard 100 Two-Proposal',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Hazard Phase', start_hour: 0, end_hour: 2000 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Hazard Crew', hourly_rate: 100 }),
        headers
      )
    );

    for (let i = 0; i < 3; i++) {
      const wo = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({ task_type: `Seed ${i}`, start_hour: i * 300, end_hour: i * 300 + 200 }),
          headers
        )
      );
      const c = getSuccessData<CrewContract>(
        await apiClient.createContract(project.id, createContractPayload(wo.id, crew.id), headers)
      );
      expect(c.is_hazardous_pay_rate).toBe(true);
    }

    const before = getSuccessData<UrbanRenewalProject>(await apiClient.getProject(project.id, headers));
    expect(before.community_disruption_index).toBe(75);

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'HA-B', start_hour: 1200, end_hour: 1400 }),
        headers
      )
    );
    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({ task_type: 'HA-C', start_hour: 1500, end_hour: 1700 }),
        headers
      )
    );

    const [a, b] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(orderA.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
    ]);

    const statuses = [a.status, b.status].sort();
    expect(statuses).toEqual([201, 403]);
    const loser = a.status === 403 ? a : b;
    validateErrorEnvelope(loser, { expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED });
  });
  it('three-way disruption race: cancel hazardous A while two hazardous proposals B and C compete', async () => {
    const headers = buildAuthHeaders('three-way-disruption');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Three-Way Disruption Race',
          renovation_budget: 500_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Disruption Phase', start_hour: 0, end_hour: 1000 }),
        headers
      )
    );

    const crewA = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CrewA', hourly_rate: 100 }),
        headers
      )
    );
    const crewB = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CrewB', hourly_rate: 100 }),
        headers
      )
    );
    const crewC = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CrewC', hourly_rate: 100 }),
        headers
      )
    );

    const setupOrders: WorkOrder[] = [];
    for (let i = 0; i < 3; i++) {
      const order = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({
            task_type: 'Hazard Setup',
            start_hour: i * 200,
            end_hour: i * 200 + 190
          }),
          headers
        )
      );
      setupOrders.push(order);
    }

    for (let i = 0; i < 3; i++) {
      const contract = getSuccessData<CrewContract>(
        await apiClient.createContract(
          project.id,
          createContractPayload(setupOrders[i].id, [crewA, crewB, crewC][i].id),
          headers
        )
      );
      expect(contract.is_hazardous_pay_rate).toBe(true);
    }

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Hazard A',
          start_hour: 600,
          end_hour: 800
        }),
        headers
      )
    );
    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderA.id, crewA.id),
        headers
      )
    );
    expect(contractA.is_hazardous_pay_rate).toBe(true);

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectBefore.community_disruption_index).toBe(100);

    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Hazard B',
          start_hour: 810,
          end_hour: 1000
        }),
        headers
      )
    );
    const orderC = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Hazard C',
          start_hour: 810,
          end_hour: 1000
        }),
        headers
      )
    );

    const [cancelRes, proposeBRes, proposeCRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractA.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crewB.id), headers),
      apiClient.createContract(project.id, createContractPayload(orderC.id, crewC.id), headers),
    ]);

    expect(cancelRes.status).toBe(200);

    const proposalStatuses = [proposeBRes.status, proposeCRes.status].sort();
    expect(proposalStatuses).toEqual([201, 403]);

    const loser = proposeBRes.status === 403 ? proposeBRes : proposeCRes;
    validateErrorEnvelope(loser, {
      expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED
    });

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    expect(projectAfter.community_disruption_index).toBe(100);
  });

  it('two proposals straddling 160h boundary for same crew: single hazard classification', async () => {
    const headers = buildAuthHeaders('160h-boundary-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: '160h Boundary Race',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Boundary Phase', start_hour: 0, end_hour: 500 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'BoundaryCrew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew.id),
        headers
      )
    );
    expect(seedContract.is_hazardous_pay_rate).toBe(false);

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Boundary Work 1',
          start_hour: 200,
          end_hour: 215
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Boundary Work 2',
          start_hour: 220,
          end_hour: 235
        }),
        headers
      )
    );

    const [res1, res2] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers),
    ]);

    expect(res1.status).toBe(201);
    expect(res2.status).toBe(201);

    const contract1 = getSuccessData<CrewContract>(res1);
    const contract2 = getSuccessData<CrewContract>(res2);

    expect(contract1.is_hazardous_pay_rate).toBe(true);
    expect(contract2.is_hazardous_pay_rate).toBe(true);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.community_disruption_index).toBe(50);
  });

  it('cancel A vs propose B at the 160h hazard boundary: single hazard outcome', async () => {
    const headers = buildAuthHeaders('cancel-propose-160h');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cancel Propose 160h',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Cancel Boundary Phase', start_hour: 0, end_hour: 400 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'CancelCrew', hourly_rate: 100 }),
        headers
      )
    );

    const seed = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Initial Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seed.id, crew.id),
        headers
      )
    );

    const orderA = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Order A',
          start_hour: 200,
          end_hour: 210
        }),
        headers
      )
    );
    const contractA = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(orderA.id, crew.id),
        headers
      )
    );
    expect(contractA.is_hazardous_pay_rate).toBe(false);

    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Order B',
          start_hour: 250,
          end_hour: 260
        }),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [cancelRes, proposeRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractA.id, headers),
      apiClient.createContract(project.id, createContractPayload(orderB.id, crew.id), headers),
    ]);

    expect(cancelRes.status).toBe(200);
    expect(proposeRes.status).toBe(201);

    const contractB = getSuccessData<CrewContract>(proposeRes);
    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    if (contractB.is_hazardous_pay_rate) {

      expect(projectAfter.community_disruption_index).toBe(projectBefore.community_disruption_index + 25);
    } else {

      expect(projectAfter.community_disruption_index).toBe(projectBefore.community_disruption_index);
    }
  });

  it('two concurrent proposals straddling 160h boundary: exactly one hazardous; +25 once', async () => {
    const headers = buildAuthHeaders('160h-proposals-single-hazard');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: '160h Proposals Single Hazard',
          renovation_budget: 200_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Boundary Phase', start_hour: 0, end_hour: 400 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'Boundary Crew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Seed Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew.id),
        headers
      )
    );

    getSuccessData(await apiClient.verifySpecialization(project.id, seedContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, seedContract.id, headers));

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Boundary Work 1',
          start_hour: 200,
          end_hour: 210
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Boundary Work 2',
          start_hour: 220,
          end_hour: 230
        }),
        headers
      )
    );

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [res1, res2] = await Promise.all([
      apiClient.createContract(project.id, createContractPayload(order1.id, crew.id), headers),
      apiClient.createContract(project.id, createContractPayload(order2.id, crew.id), headers),
    ]);

    expect([201, 201]).toContain(res1.status);
    expect([201, 201]).toContain(res2.status);

    const c1 = getSuccessData<CrewContract>(res1);
    const c2 = getSuccessData<CrewContract>(res2);

    const hazardousCount = [c1.is_hazardous_pay_rate ? 1 : 0, c2.is_hazardous_pay_rate ? 1 : 0].reduce((a, b) => a + b, 0);
    expect(hazardousCount).toBe(1);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.community_disruption_index - projectBefore.community_disruption_index).toBe(25);
  });

  it('schedule vs schedule at 160h boundary: both become hazardous with exact ledgers', async () => {
    const headers = buildAuthHeaders('schedule-schedule-160h');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Schedule Schedule 160h',
          renovation_budget: 300_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Schedule Phase', start_hour: 0, end_hour: 400 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'ScheduleCrew', hourly_rate: 100 }),
        headers
      )
    );

    const seedOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Base Work',
          start_hour: 0,
          end_hour: 150
        }),
        headers
      )
    );
    const seedContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(seedOrder.id, crew.id),
        headers
      )
    );
    getSuccessData(await apiClient.verifySpecialization(project.id, seedContract.id, headers));
    getSuccessData(await apiClient.scheduleWork(project.id, seedContract.id, headers));

    const order1 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Schedule Work 1',
          start_hour: 200,
          end_hour: 215
        }),
        headers
      )
    );
    const order2 = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Schedule Work 2',
          start_hour: 220,
          end_hour: 235
        }),
        headers
      )
    );

    const contract1 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order1.id, crew.id),
        headers
      )
    );
    const contract2 = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        createContractPayload(order2.id, crew.id),
        headers
      )
    );

    expect(contract1.is_hazardous_pay_rate).toBe(true);
    expect(contract2.is_hazardous_pay_rate).toBe(true);

    getSuccessData(await apiClient.verifySpecialization(project.id, contract1.id, headers));
    getSuccessData(await apiClient.verifySpecialization(project.id, contract2.id, headers));

    const projectBeforeSchedule = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const [schedule1Res, schedule2Res] = await Promise.all([
      apiClient.scheduleWork(project.id, contract1.id, headers),
      apiClient.scheduleWork(project.id, contract2.id, headers),
    ]);

    expect(schedule1Res.status).toBe(200);
    expect(schedule2Res.status).toBe(200);

    const final1 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract1.id, headers)
    );
    const final2 = getSuccessData<CrewContract>(
      await apiClient.getContract(project.id, contract2.id, headers)
    );

    expect(final1.is_hazardous_pay_rate).toBe(true);
    expect(final2.is_hazardous_pay_rate).toBe(true);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAfter.community_disruption_index).toBe(
      projectBeforeSchedule.community_disruption_index
    );

    const finalOrder1 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order1.id, headers)
    );
    const finalOrder2 = getSuccessData<WorkOrder>(
      await apiClient.getWorkOrder(project.id, phase.id, order2.id, headers)
    );
    expect(finalOrder1.status).toBe('CONTRACTED');
    expect(finalOrder2.status).toBe('CONTRACTED');
  });

  it('cancel hazardous A frees disruption headroom vs propose hazardous B', async () => {
    const headers = buildAuthHeaders('cancel-frees-disruption');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Cancel Frees Disruption',
          renovation_budget: 500_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Disruption Freedom', start_hour: 0, end_hour: 1000 }),
        headers
      )
    );

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'DisruptCrew1', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'DisruptCrew2', hourly_rate: 100 }),
        headers
      )
    );

    for (let i = 0; i < 4; i++) {
      const order = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({
            task_type: `Setup ${i}`,
            start_hour: i * 200,
            end_hour: i * 200 + 180
          }),
          headers
        )
      );
      const contract = getSuccessData<CrewContract>(
        await apiClient.createContract(
          project.id,
          createContractPayload(order.id, i % 2 === 0 ? crew1.id : crew2.id),
          headers
        )
      );
      if (i < 3) {

        getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
        getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));
      }
    }

    const projectAt100 = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );
    expect(projectAt100.community_disruption_index).toBe(100);

    const contracts = getSuccessData<CrewContract[]>(
      await apiClient.getContracts(project.id, headers)
    );
    const contractA = contracts.find(c => c.status === 'PROPOSED')!;
    expect(contractA).toBeDefined();

    const orderB = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'New Hazard B',
          start_hour: 850,
          end_hour: 1000
        }),
        headers
      )
    );

    const [cancelRes, proposeRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractA.id, headers),
      apiClient.createContract(
        project.id,
        { ...createContractPayload(orderB.id, crew2.id), permit_waiver_used: false },
        headers
      ),
    ]);

    if (cancelRes.status === 200 && proposeRes.status === 201) {

      const contractB = getSuccessData<CrewContract>(proposeRes);
      expect(contractB.is_hazardous_pay_rate).toBe(true);
      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.community_disruption_index).toBe(100);
    } else if (proposeRes.status === 403) {

      validateErrorEnvelope(proposeRes, {
        expectedErrorId: ApiErrorId.ERR_DISRUPTION_INDEX_THRESHOLD_BREACHED
      });
      expect(cancelRes.status).toBe(200);
      const projectAfter = getSuccessData<UrbanRenewalProject>(
        await apiClient.getProject(project.id, headers)
      );
      expect(projectAfter.community_disruption_index).toBe(75);
    } else {
      fail(`Unexpected outcome: cancel ${cancelRes.status}, propose ${proposeRes.status}`);
    }
  });

  it('concurrent hazardous propose + hazardous cancel + waiver-penalty case yields exact ledgers', async () => {
    const headers = buildAuthHeaders('waiver-penalty-race');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Waiver Penalty Race',
          renovation_budget: 500_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Waiver Phase', start_hour: 0, end_hour: 1000 }),
        headers
      )
    );

    const crew1 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'WaiverCrew1', hourly_rate: 100 }),
        headers
      )
    );
    const crew2 = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'WaiverCrew2', hourly_rate: 100 }),
        headers
      )
    );

    for (let i = 0; i < 3; i++) {
      const order = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({
            task_type: `Waiver Setup ${i}`,
            start_hour: i * 200,
            end_hour: i * 200 + 180
          }),
          headers
        )
      );
      const contract = getSuccessData<CrewContract>(
        await apiClient.createContract(
          project.id,
          createContractPayload(order.id, crew1.id),
          headers
        )
      );
      getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
      getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));
    }

    const orderWithWaiver = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Waivered Work',
          start_hour: 700,
          end_hour: 900
        }),
        headers
      )
    );

    const contractWithWaiver = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        { ...createContractPayload(orderWithWaiver.id, crew1.id), permit_waiver_used: true },
        headers
      )
    );
    expect(contractWithWaiver.is_hazardous_pay_rate).toBe(true);
    expect(contractWithWaiver.permit_waiver_penalty_applied).toBe(false);

    const projectBefore = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    expect(projectBefore.community_disruption_index).toBe(100);

    const orderNew = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'New Work',
          start_hour: 920,
          end_hour: 1000
        }),
        headers
      )
    );

    const [cancelRes, proposeRes] = await Promise.all([
      apiClient.cancelContract(project.id, contractWithWaiver.id, headers),
      apiClient.createContract(
        project.id,
        createContractPayload(orderNew.id, crew2.id),
        headers
      ),
    ]);

    expect(cancelRes.status).toBe(200);
    expect(proposeRes.status).toBe(201);

    const projectAfter = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    const expectedIndex = projectBefore.community_disruption_index - 25 +
      (getSuccessData<CrewContract>(proposeRes).is_hazardous_pay_rate ? 25 : 0);

    expect(projectAfter.community_disruption_index).toBe(expectedIndex);
  });

  it('waiver penalty true → cancellation reversal removes both 25 hazard and 75 penalty', async () => {
    const headers = buildAuthHeaders('waiver-penalty-true-reversal');

    const project = getSuccessData<UrbanRenewalProject>(
      await apiClient.createProject(
        createProjectPayload({
          project_name: 'Waiver Penalty True Reversal',
          renovation_budget: 500_000
        }),
        headers
      )
    );
    getSuccessData(await apiClient.beginWork(project.id, headers));

    const phase = getSuccessData<RenovationPhase>(
      await apiClient.createPhase(
        project.id,
        createPhasePayload({ name: 'Penalty Reversal Phase', start_hour: 0, end_hour: 1000 }),
        headers
      )
    );

    const crew = getSuccessData<RenovationCrew>(
      await apiClient.createCrew(
        project.id,
        createCrewPayload({ crew_name: 'PenaltyCrew', hourly_rate: 100 }),
        headers
      )
    );

    for (let i = 0; i < 4; i++) {
      const order = getSuccessData<WorkOrder>(
        await apiClient.createWorkOrder(
          project.id,
          phase.id,
          createWorkOrderPayload({
            task_type: `Setup ${i}`,
            start_hour: i * 200,
            end_hour: i * 200 + 180
          }),
          headers
        )
      );
      const contract = getSuccessData<CrewContract>(
        await apiClient.createContract(
          project.id,
          createContractPayload(order.id, crew.id),
          headers
        )
      );
      getSuccessData(await apiClient.verifySpecialization(project.id, contract.id, headers));
      getSuccessData(await apiClient.scheduleWork(project.id, contract.id, headers));
    }

    const waiveredOrder = getSuccessData<WorkOrder>(
      await apiClient.createWorkOrder(
        project.id,
        phase.id,
        createWorkOrderPayload({
          task_type: 'Waivered Breach Work',
          start_hour: 800,
          end_hour: 1000
        }),
        headers
      )
    );

    const waiveredContract = getSuccessData<CrewContract>(
      await apiClient.createContract(
        project.id,
        { ...createContractPayload(waiveredOrder.id, crew.id), permit_waiver_used: true },
        headers
      )
    );
    expect(waiveredContract.is_hazardous_pay_rate).toBe(true);
    expect(waiveredContract.permit_waiver_penalty_applied).toBe(true);

    const projectBeforeCancel = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    expect(projectBeforeCancel.community_disruption_index).toBe(200);

    getSuccessData(await apiClient.cancelContract(project.id, waiveredContract.id, headers));

    const projectAfterCancel = getSuccessData<UrbanRenewalProject>(
      await apiClient.getProject(project.id, headers)
    );

    expect(projectAfterCancel.community_disruption_index).toBe(100);
  });
});
